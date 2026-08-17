"""On-demand Gate Explainer — LLM paraphrase of an FP-gate decision.

Deliberately NOT part of any background pipeline: gated (parked/queued)
incidents cost zero inference by design, and running a model on every one of
them would invert that economics (noise dominates real signal streams). This
agent runs only when a human clicks "Explain with AI" on the dashboard, so
spend scales with human curiosity, not signal volume. The result is persisted
on the incident so repeat clicks are free.

The prompt pins the model to the deterministic score breakdown that the gate
actually produced — its job is to *translate* the decision for a non-expert,
never to invent causes the arithmetic doesn't contain.
"""

import json
import logging

from app.llm import UNTRUSTED_DATA_NOTICE, get_client, get_model, wrap_untrusted
from app.models import Incident

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "You are a senior SOC analyst explaining an automated triage decision to a "
    "colleague who is not a security expert. You are given the deterministic "
    "false-positive-gate score breakdown that produced the decision, plus the "
    "raw signal data for context.\n"
    "Rules:\n"
    "- Write 3-5 plain-English sentences. No headings, no lists, no jargon.\n"
    "- Stay strictly faithful to the provided score breakdown. Do NOT invent "
    "causes, intent, or facts that are not in it — the raw signal data is "
    "context only, not grounds for new conclusions.\n"
    "- End by saying what happens next for an incident in this state.\n"
    "Respond with the explanation text only."
) + UNTRUSTED_DATA_NOTICE


def generate_explanation(incident: Incident) -> str:
    """One LLM call. Raises on failure — the router turns that into a 502."""
    trusted_context = (
        f"Gate decision: status={incident.status}, score={incident.fp_score}.\n"
        f"Exact score breakdown: {incident.fp_decision_reason}\n"
        f"Deterministic explanation of the rules that fired: {incident.fp_explanation}"
    )
    untrusted_payload = wrap_untrusted(
        json.dumps(
            {
                "resource_name": incident.resource_name,
                "timeline": incident.timeline,
            }
        )
    )
    response = get_client().chat.completions.create(
        model=get_model(),
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"{trusted_context}\n\nRaw signal data:\n{untrusted_payload}"},
        ],
        timeout=30,
    )
    text = (response.choices[0].message.content or "").strip()
    if not text:
        raise RuntimeError("LLM returned an empty explanation")
    return text
