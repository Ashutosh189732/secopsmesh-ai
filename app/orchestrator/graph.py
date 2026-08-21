"""LangGraph Orchestrator — Day 3.

Wakes up for each `investigating` incident and loops
plan_investigation -> fetch_evidence -> check_enough, deciding each round
whether more mocked evidence is worth fetching, until either the planner
says "enough", the connector list is exhausted, 3 items are collected, or a
hard iteration cap (5) is hit.

The whole run is wrapped in a 90-second wall-clock guard (the plan's Gap 2/4
requirement to never hang on a flaky LLM call). On timeout we don't just
throw the run away: fetch_evidence writes into a `shared` dict as it goes, so
whatever evidence was collected before the deadline is still returned with
`guard_triggered=True` instead of being lost.
"""

import concurrent.futures
import json
import logging

from langchain_openai import ChatOpenAI
from langgraph.graph import END, StateGraph

from app import config
from app.llm import UNTRUSTED_DATA_NOTICE, extract_json, wrap_untrusted
from app.orchestrator import connectors
from app.orchestrator.state import InvestigationState

logger = logging.getLogger(__name__)

RUN_TIMEOUT_SECONDS = 90
MAX_ITERATIONS = 5
MAX_EVIDENCE_ITEMS = 3


def _build_planner_prompt(agentic_mode: bool) -> str:
    """Build planner system prompt based on connector selection mode."""
    base = (
        "You are the evidence-gathering planner for a SOC incident investigation. "
        "Given an incident and the evidence already collected, decide whether more "
        "evidence is needed and, if so, which single connector to query next from "
        "the remaining list. Two or three well-chosen items are normally enough to "
        "explain root cause and impact - don't over-collect.\n"
    )

    if agentic_mode:
        # Agentic mode: provide connector descriptions and comprehensive guidance
        base += (
            "\nAvailable connectors (confidence scores reflect data reliability):\n"
            "- azure_monitor (0.95): Deployment logs, config changes, resource metrics, release history\n"
            "- kubernetes (0.90): Pod logs, namespace events, container metrics, volume mounts\n"
            "- github_commits (0.85): Code/config changes, deployment history, recent commits\n"
            "- iam_logs (0.80): API calls, authentication events, access patterns, unusual volume\n\n"

            "SIGNAL TYPE → CONNECTOR GUIDANCE:\n"
            "Match connectors to the incident's signal type and context:\n\n"

            "PublicStorageBucket:\n"
            "  - azure_monitor: Config changes that exposed storage (highest priority)\n"
            "  - github_commits: Terraform/IaC changes that modified ACLs\n"
            "  - iam_logs: Access pattern spikes after exposure\n"
            "  - kubernetes: Pod activity if storage mounted to containers\n\n"

            "UnauthorizedAPICall:\n"
            "  - iam_logs: Auth attempts, API call patterns (highest priority)\n"
            "  - azure_monitor: Deployment/policy changes that granted access\n"
            "  - github_commits: IAM policy or role changes in code\n"
            "  - kubernetes: Service account activity if pods involved\n\n"

            "LargeDataUpload:\n"
            "  - kubernetes: Pod logs, volume writes (highest priority for container workloads)\n"
            "  - azure_monitor: Volume config changes, mount events\n"
            "  - iam_logs: API calls for data transfer after upload\n"
            "  - github_commits: Training job or pipeline config changes\n\n"

            "EVIDENCE DIVERSITY:\n"
            "Prioritize different TYPES of evidence (mix deployment logs + runtime behavior + code changes + access patterns) "
            "over similar sources. If timeline already shows kubernetes events, consider azure_monitor or github_commits next "
            "to capture a different perspective. Avoid redundant evidence from the same layer.\n\n"

            "CONTEXT-DRIVEN SELECTION:\n"
            "Use incident details to refine choices:\n"
            "  - API names: 'keyvault' or 'secrets' → iam_logs priority\n"
            "  - Actor type 'service' + kubernetes source → kubernetes connector relevant\n"
            "  - Blocked outcomes: May need less evidence (already mitigated)\n"
            "  - High severity + success outcome: Prioritize deployment history (azure_monitor/github)\n\n"

            "CONFIDENCE GUIDANCE:\n"
            "Higher confidence sources (azure_monitor 0.95, kubernetes 0.90) are preferred when EQUALLY relevant. "
            "However, choose lower confidence sources (github_commits 0.85, iam_logs 0.80) when they're MORE relevant "
            "to the signal type - e.g., iam_logs (0.80) beats azure_monitor (0.95) for UnauthorizedAPICall root cause.\n\n"
        )

    base += (
        'Respond with ONLY a JSON object, no prose: {"action": "fetch", "connector": "<name>"} '
        'or {"action": "enough"}.'
    )

    return base + UNTRUSTED_DATA_NOTICE


def _llm() -> ChatOpenAI:
    settings = config.settings
    if not settings.openrouter_api_key:
        raise RuntimeError("OPENROUTER_API_KEY is not set.")
    return ChatOpenAI(
        base_url=settings.openrouter_base_url,
        api_key=settings.openrouter_api_key,
        model=settings.openrouter_model,
        timeout=20,
        max_retries=1,
    )


def _extract_relevant_details(signal_type: str, details: dict) -> dict:
    """Extract signal-type-specific fields from details dict.

    Filters details to include only fields relevant to connector selection,
    avoiding noisy or irrelevant data.
    """
    if not details:
        return {}

    # Define relevant fields per signal type
    relevant_fields = {
        "PublicStorageBucket": ["bucket_acl", "public_network_access", "allow_blob_public_access"],
        "UnauthorizedAPICall": ["caller", "api", "call_count_last_hour", "baseline_call_count_last_hour"],
        "LargeDataUpload": ["size_gb", "file_name", "upload_rate_mbps"],
    }

    # Get relevant fields for this signal type, or all fields if unknown type
    fields = relevant_fields.get(signal_type)
    if fields is None:
        return details  # Unknown signal type - include all details

    return {k: v for k, v in details.items() if k in fields}


def _summarize_timeline_sources(timeline: list) -> set[str]:
    """Extract unique sources from timeline events.

    Returns set of sources (e.g., {'kubernetes', 'azure_monitor'}) to help
    LLM understand which evidence types are already represented.
    """
    if not timeline:
        return set()

    sources = set()
    for event in timeline:
        source = event.get("source")
        if source:
            sources.add(source)

    return sources


def _build_context_payload(
    signal_type: str,
    resource_name: str,
    severity: str,
    details: dict,
    timeline: list,
    evidence: list,
    remaining_connectors: list[str]
) -> str:
    """Build context payload with incident details, timeline, and evidence collected.

    Returns a structured string that will be wrapped in <untrusted_data> tags.
    """
    # Extract relevant details fields based on signal type
    relevant_details = _extract_relevant_details(signal_type, details)

    # Summarize timeline sources to encourage diversity
    timeline_sources = _summarize_timeline_sources(timeline)

    # Limit timeline to most recent 5 events to avoid token bloat
    timeline_subset = timeline[-5:] if len(timeline) > 5 else timeline

    payload = (
        f"INCIDENT OVERVIEW:\n"
        f"Signal Type: {signal_type}\n"
        f"Resource: {resource_name}\n"
        f"Severity: {severity}\n"
    )

    if relevant_details:
        payload += f"\nINCIDENT DETAILS:\n{json.dumps(relevant_details, indent=2)}\n"

    if timeline_subset:
        payload += f"\nTIMELINE ({len(timeline_subset)} events):\n{json.dumps(timeline_subset, indent=2)}\n"
        if timeline_sources:
            payload += f"\nTimeline includes signals from: {', '.join(sorted(timeline_sources))}\n"

    if evidence:
        payload += f"\nEVIDENCE COLLECTED SO FAR ({len(evidence)} items):\n{json.dumps(evidence, indent=2)}\n"

    payload += f"\nREMAINING CONNECTORS: {remaining_connectors}\n"

    return payload


def _plan_investigation(state: InvestigationState) -> dict:
    if not state["remaining_connectors"] or state["iteration"] >= MAX_ITERATIONS:
        return {"next_action": "enough", "next_connector": None}

    try:
        evidence_summary = [
            {"connector": e["connector"], "confidence": e["confidence"], "data": e["data"]}
            for e in state["evidence"]
        ]

        # Build context payload with incident details and timeline
        context_payload = _build_context_payload(
            signal_type=state["signal_type"],
            resource_name=state["resource_name"],
            severity=state["severity"],
            details=state["details"],
            timeline=state["timeline"],
            evidence=evidence_summary,
            remaining_connectors=state["remaining_connectors"]
        )
        user_msg = wrap_untrusted(context_payload)

        response = _llm().invoke(
            [
                {"role": "system", "content": _build_planner_prompt(state.get("agentic_mode", False))},
                {"role": "user", "content": user_msg},
            ]
        )
        decision = extract_json(response.content)
        connector = decision.get("connector")
        if decision.get("action") == "fetch" and connector in state["remaining_connectors"]:
            return {"next_action": "fetch", "next_connector": connector}
        return {"next_action": "enough", "next_connector": None}
    except Exception as exc:
        # LLM unreachable / bad JSON / anything else — never let planning
        # failure hang the graph. Fall back to the deterministic connector
        # order already selected for this incident type, but log it loudly:
        # a silently-swallowed failure here looks identical to a successful
        # LLM decision in the output, which is exactly what happened during
        # Day 3's first "verified" run (placeholder API key, never noticed).
        logger.warning(
            "orchestrator planner LLM call failed for incident %s, falling back "
            "to deterministic connector order: %s: %s",
            state["incident_id"],
            type(exc).__name__,
            exc,
        )
        return {"next_action": "fetch", "next_connector": state["remaining_connectors"][0]}


def _route_after_plan(state: InvestigationState) -> str:
    return "fetch" if state["next_action"] == "fetch" else "end"


def _route_after_check(state: InvestigationState) -> str:
    if (
        state["guard_triggered"]
        or not state["remaining_connectors"]
        or len(state["evidence"]) >= MAX_EVIDENCE_ITEMS
    ):
        return "end"
    return "loop"


def _build_graph(shared: dict):
    def fetch_evidence(state: InvestigationState) -> dict:
        connector = state["next_connector"]

        # Build context dict for scenario-aware evidence generation
        context = {
            "resource_name": state["resource_name"],
            "signal_type": state["signal_type"],
            "severity": state["severity"],
            "details": state["details"],
            "timeline": state["timeline"],
        }

        item = connectors.fetch(connector, context)
        # Stable per-incident id (ev1, ev2, ...) so the Day 4 Root Cause Agent
        # can cite specific evidence items in evidence_ids_cited.
        item["id"] = f"ev{len(state['evidence']) + 1}"
        evidence = [*state["evidence"], item]
        connectors_queried = [*state["connectors_queried"], connector]
        # Mirrored into `shared` immediately so a 90s timeout on a later LLM
        # planning call doesn't lose evidence already fetched this run.
        shared["evidence"] = evidence
        shared["connectors_queried"] = connectors_queried
        return {
            "evidence": evidence,
            "connectors_queried": connectors_queried,
            "remaining_connectors": [c for c in state["remaining_connectors"] if c != connector],
            "iteration": state["iteration"] + 1,
        }

    def check_enough(state: InvestigationState) -> dict:
        return {"guard_triggered": state["iteration"] >= MAX_ITERATIONS}

    graph = StateGraph(InvestigationState)
    graph.add_node("plan_investigation", _plan_investigation)
    graph.add_node("fetch_evidence", fetch_evidence)
    graph.add_node("check_enough", check_enough)

    graph.set_entry_point("plan_investigation")
    graph.add_conditional_edges(
        "plan_investigation", _route_after_plan, {"fetch": "fetch_evidence", "end": END}
    )
    graph.add_edge("fetch_evidence", "check_enough")
    graph.add_conditional_edges(
        "check_enough", _route_after_check, {"loop": "plan_investigation", "end": END}
    )
    return graph.compile()


def run_investigation(
    incident_id: int,
    resource_name: str,
    signal_type: str,
    severity: str,
    details: dict,
    timeline: list,
) -> dict:
    """Run the orchestrator for one incident. Always returns within ~90s."""
    shared: dict = {"evidence": [], "connectors_queried": []}
    compiled = _build_graph(shared)

    # Read config to determine connector selection mode
    agentic_mode = config.settings.use_agentic_connector_selection

    initial: InvestigationState = {
        "incident_id": incident_id,
        "resource_name": resource_name,
        "signal_type": signal_type,
        "severity": severity,
        "details": details,
        "timeline": timeline,
        "evidence": [],
        "connectors_queried": [],
        "remaining_connectors": connectors.connector_order_for(signal_type, agentic=agentic_mode),
        "iteration": 0,
        "guard_triggered": False,
        "next_action": "",
        "next_connector": None,
        "agentic_mode": agentic_mode,
    }

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(compiled.invoke, initial, {"recursion_limit": 25})
        try:
            result = future.result(timeout=RUN_TIMEOUT_SECONDS)
            return {
                "evidence": result["evidence"],
                "connectors_queried": result["connectors_queried"],
                "iteration": result["iteration"],
                "guard_triggered": result["guard_triggered"],
            }
        except concurrent.futures.TimeoutError:
            return {
                "evidence": shared["evidence"],
                "connectors_queried": shared["connectors_queried"],
                "iteration": len(shared["evidence"]),
                "guard_triggered": True,
            }
