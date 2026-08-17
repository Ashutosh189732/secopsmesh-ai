"""Risk Assessment — Day 5.

The score and severity bucket are pure Python — deterministic, auditable,
and computed even if the LLM call below fails. Only the two narrative
fields (business_impact, compliance_impact) come from Claude Sonnet 5, kept
in non-technical language for an executive audience.
"""

import json
import logging

from pydantic import BaseModel

from app.llm import (
    UNTRUSTED_DATA_NOTICE,
    extract_json,
    get_client,
    get_model,
    wrap_untrusted,
)

logger = logging.getLogger(__name__)

SEVERITY_WEIGHT = {"critical": 40, "high": 30, "medium": 15, "low": 5}
CORRELATED_COUNT_CAP = 20
CORRELATED_COUNT_PER_SIGNAL = 5
GDPR_FLAG_POINTS = 20
AFFECTED_RESOURCES_CAP = 20
AFFECTED_RESOURCES_PER_RESOURCE = 10


class RiskNarrative(BaseModel):
    business_impact: str
    compliance_impact: str


SYSTEM_PROMPT = (
    "You are briefing a non-technical executive on a security incident. Given "
    "the incident's root cause, risk severity, and the compliance policies it "
    "touches, write two short narratives in plain business language (no "
    "jargon, no technical terms like 'API' or 'bucket ACL' if avoidable):\n"
    "- business_impact: 2 sentences on what happened and why it matters to the business.\n"
    "- compliance_impact: 1-2 sentences on regulatory/compliance exposure, "
    "naming the specific regulations involved.\n"
    "Respond with ONLY a JSON object, no prose, no markdown fences: "
    '{"business_impact": string, "compliance_impact": string}'
) + UNTRUSTED_DATA_NOTICE

FALLBACK_NARRATIVE = {
    "business_impact": (
        "Automated narrative generation failed; a human analyst should review "
        "this incident's business impact directly from the root cause and evidence."
    ),
    "compliance_impact": (
        "Automated narrative generation failed; review the cited policies directly."
    ),
}


def _affected_resources_count(incident_details: dict, evidence: list, resource_name: str) -> int:
    resources = {resource_name}
    for item in evidence:
        data = item.get("data", {})
        if isinstance(data.get("resource"), str):
            resources.add(data["resource"])
    return len(resources)


def _score(severity: str, correlated_count: int, gdpr_flag: bool, affected_resources_count: int) -> int:
    severity_points = SEVERITY_WEIGHT.get(severity, 0)
    correlated_points = min(CORRELATED_COUNT_CAP, correlated_count * CORRELATED_COUNT_PER_SIGNAL)
    gdpr_points = GDPR_FLAG_POINTS if gdpr_flag else 0
    affected_points = min(
        AFFECTED_RESOURCES_CAP, affected_resources_count * AFFECTED_RESOURCES_PER_RESOURCE
    )
    return severity_points + correlated_points + gdpr_points + affected_points


def _severity_bucket(score: int) -> str:
    if score >= 80:
        return "Critical"
    if score >= 60:
        return "High"
    if score >= 35:
        return "Medium"
    return "Low"


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


def _generate_narrative(
    signal_type: str, resource_name: str, root_cause: dict, severity: str, gdpr_flag: bool
) -> dict:
    user_msg = wrap_untrusted(
        json.dumps(
            {
                "signal_type": signal_type,
                "resource_name": resource_name,
                "severity": severity,
                "gdpr_flag": gdpr_flag,
                "root_cause": root_cause.get("root_cause"),
            }
        )
    )
    for attempt in range(2):
        try:
            raw = _call_llm(user_msg)
            parsed = extract_json(raw)
            return RiskNarrative(**parsed).model_dump()
        except Exception as exc:
            # Any failure retries once then falls back to a neutral narrative;
            # the deterministic score/severity above is already computed.
            logger.warning(
                "risk narrative attempt %d/2 failed: %s: %s", attempt + 1, type(exc).__name__, exc
            )
    return dict(FALLBACK_NARRATIVE)


def assess_risk(
    signal_type: str,
    resource_name: str,
    severity: str,
    correlated_count: int,
    details: dict,
    evidence: list,
    root_cause: dict,
) -> dict:
    """Deterministic score/severity (always computed) + LLM narrative
    (falls back gracefully). Never raises.
    """
    gdpr_flag = bool(root_cause.get("gdpr_flag", False))
    affected_resources_count = _affected_resources_count(details, evidence, resource_name)

    score = _score(severity, correlated_count, gdpr_flag, affected_resources_count)
    narrative = _generate_narrative(signal_type, resource_name, root_cause, severity, gdpr_flag)

    return {
        "severity": _severity_bucket(score),
        "score": score,
        "gdpr_flag": gdpr_flag,
        "affected_estimate": f"{affected_resources_count} resource(s) directly implicated by evidence",
        **narrative,
    }
