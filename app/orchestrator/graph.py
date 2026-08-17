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

PLANNER_SYSTEM = (
    "You are the evidence-gathering planner for a SOC incident investigation. "
    "Given an incident and the evidence already collected, decide whether more "
    "evidence is needed and, if so, which single connector to query next from "
    "the remaining list. Two or three well-chosen items are normally enough to "
    "explain root cause and impact - don't over-collect.\n"
    'Respond with ONLY a JSON object, no prose: {"action": "fetch", "connector": "<name>"} '
    'or {"action": "enough"}.'
) + UNTRUSTED_DATA_NOTICE


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


def _plan_investigation(state: InvestigationState) -> dict:
    if not state["remaining_connectors"] or state["iteration"] >= MAX_ITERATIONS:
        return {"next_action": "enough", "next_connector": None}

    try:
        evidence_summary = [
            {"connector": e["connector"], "confidence": e["confidence"], "data": e["data"]}
            for e in state["evidence"]
        ]
        user_msg = wrap_untrusted(
            f"Incident: {state['signal_type']} on resource '{state['resource_name']}' "
            f"(severity={state['severity']}).\n"
            f"Evidence collected so far ({len(evidence_summary)} items): "
            f"{json.dumps(evidence_summary)}\n"
            f"Remaining connectors available: {state['remaining_connectors']}"
        )
        response = _llm().invoke(
            [
                {"role": "system", "content": PLANNER_SYSTEM},
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
        item = connectors.fetch(connector, state["resource_name"])
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


def run_investigation(incident_id: int, resource_name: str, signal_type: str, severity: str) -> dict:
    """Run the orchestrator for one incident. Always returns within ~90s."""
    shared: dict = {"evidence": [], "connectors_queried": []}
    compiled = _build_graph(shared)

    initial: InvestigationState = {
        "incident_id": incident_id,
        "resource_name": resource_name,
        "signal_type": signal_type,
        "severity": severity,
        "evidence": [],
        "connectors_queried": [],
        "remaining_connectors": connectors.connector_order_for(signal_type),
        "iteration": 0,
        "guard_triggered": False,
        "next_action": "",
        "next_connector": None,
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
