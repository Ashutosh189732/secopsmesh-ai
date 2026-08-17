"""Root Cause Agent — Day 4 (fully addresses Gap 2).

Synthesizes the correlated timeline, trust-tagged evidence, and retrieved
policy excerpts into a structured root-cause explanation via Claude Sonnet 5
(OpenRouter). Output is validated against RootCauseOutput; a malformed
response gets one retry, then a graceful fallback so a flaky or
non-compliant LLM response never blocks the pipeline.
"""

import json
import logging

from pydantic import BaseModel, Field

from app.llm import (
    UNTRUSTED_DATA_NOTICE,
    extract_json,
    get_client,
    get_model,
    wrap_untrusted,
)

logger = logging.getLogger(__name__)


class RootCauseOutput(BaseModel):
    root_cause: str
    confidence: float = Field(ge=0.0, le=1.0)
    evidence_ids_cited: list[str] = Field(default_factory=list)
    alternative_hypotheses: list[str] = Field(default_factory=list)
    gdpr_flag: bool = False


SYSTEM_PROMPT = (
    "You are a senior security analyst investigating a SOC incident. You are given "
    "the incident timeline, evidence collected so far (each item has an 'id' and a "
    "'confidence' trust score), and relevant compliance policy excerpts. Determine "
    "the most likely root cause.\n"
    "Rules:\n"
    "- Cite the specific evidence ids that support your conclusion in evidence_ids_cited.\n"
    "- Any evidence item with confidence below 0.5 that you rely on must be explicitly "
    'named as a "low_confidence_source" within your root_cause text, not silently relied on.\n'
    "- List credible alternative_hypotheses you considered and ruled out.\n"
    "- Set gdpr_flag true only if the incident plausibly involves exposure of personal "
    "data under GDPR, based on the evidence and cited policies.\n"
    "Respond with ONLY a JSON object, no prose, no markdown fences, matching exactly:\n"
    '{"root_cause": string, "confidence": number 0-1, "evidence_ids_cited": [string], '
    '"alternative_hypotheses": [string], "gdpr_flag": boolean}'
) + UNTRUSTED_DATA_NOTICE

FALLBACK_RESULT = {
    "root_cause": "Root Cause Agent could not produce a validated result after retrying.",
    "confidence": 0.0,
    "evidence_ids_cited": [],
    "alternative_hypotheses": [],
    "gdpr_flag": False,
    "error": "root_cause_agent_failed",
}


def _call_llm(user_msg: str) -> str:
    response = get_client().chat.completions.create(
        model=get_model(),
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ],
        timeout=30,
    )
    return response.choices[0].message.content


def _build_user_message(timeline: list, evidence: list, policies: list) -> str:
    return wrap_untrusted(
        json.dumps({"timeline": timeline, "evidence": evidence, "policies": policies})
    )


def determine_root_cause(timeline: list, evidence: list, policies: list) -> dict:
    """Run the Root Cause Agent. Always returns a dict — never raises."""
    user_msg = _build_user_message(timeline, evidence, policies)

    for attempt in range(2):
        try:
            raw = _call_llm(user_msg)
            parsed = extract_json(raw)
            validated = RootCauseOutput(**parsed)
            return validated.model_dump()
        except Exception as exc:
            # Any failure — network, non-JSON, schema mismatch — retries once
            # then falls back. The agent must never raise into the worker.
            logger.warning(
                "root cause agent attempt %d/2 failed: %s: %s",
                attempt + 1,
                type(exc).__name__,
                exc,
            )

    return dict(FALLBACK_RESULT)
