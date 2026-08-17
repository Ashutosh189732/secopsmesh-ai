"""Remediation Planner — Day 5.

Produces a stepwise remediation plan from root cause + risk assessment +
top policy hits. Nothing this system produces ever executes automatically:
`requires_human_approval` is forced to True on every step in code, after
parsing — never trusted from the LLM's own output, even if the model
returns false or omits the field.

Note on "runbook excerpts" (mentioned in the plan's prompt inputs): this POC
has no runbook corpus of its own yet, so the retrieved policy excerpts serve
as the closest available process context. A dedicated runbooks/ library
would be a natural follow-up, not building one wasn't an oversight.
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

SYSTEM_PROMPT = (
    "You are a remediation planner for a SOC incident. Given the root cause, "
    "risk assessment, and relevant compliance policy excerpts, produce a "
    "stepwise remediation plan.\n"
    "Hard constraint: never include executable code, CLI commands, shell "
    "snippets, or SDK/API calls anywhere in your output. Produce only "
    "human-readable action descriptions that a person will read and carry out.\n"
    "Respond with ONLY a JSON object, no prose, no markdown fences, matching:\n"
    '{"steps": [{"step_number": int, "action": string, "owner": string, '
    '"priority": "high"|"medium"|"low", "estimated_time": string}]}\n'
    "Do not include a requires_human_approval field — every step in this system "
    "requires human approval unconditionally, regardless of what you'd otherwise suggest."
) + UNTRUSTED_DATA_NOTICE

FALLBACK_PLAN = {
    "steps": [
        {
            "step_number": 1,
            "action": (
                "Automated remediation planning failed; a human responder must "
                "manually review the root cause and risk assessment to determine "
                "next steps."
            ),
            "owner": "on-call-security",
            "priority": "high",
            "estimated_time": "unknown",
            "requires_human_approval": True,
        }
    ]
}


class RemediationStep(BaseModel):
    step_number: int
    action: str
    owner: str
    priority: str
    estimated_time: str


class RemediationPlan(BaseModel):
    steps: list[RemediationStep]


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


def plan_remediation(root_cause: dict, risk_assessment: dict, policies: list) -> dict:
    """Always returns a dict with `steps`, every step forced
    requires_human_approval=True. Never raises.
    """
    user_msg = wrap_untrusted(
        json.dumps(
            {
                "root_cause": root_cause,
                "risk_assessment": risk_assessment,
                "policies": [
                    {"policy_id": p["policy_id"], "excerpt": p["excerpt"]} for p in policies
                ],
            }
        )
    )

    for attempt in range(2):
        try:
            raw = _call_llm(user_msg)
            parsed = extract_json(raw)
            validated = RemediationPlan(**parsed)
            result = validated.model_dump()
            # Never trust the LLM on this — force it, unconditionally, in code.
            for step in result["steps"]:
                step["requires_human_approval"] = True
            return result
        except Exception as exc:
            # Any failure retries once then falls back to a manual-review plan.
            logger.warning(
                "remediation planner attempt %d/2 failed: %s: %s",
                attempt + 1,
                type(exc).__name__,
                exc,
            )

    return dict(FALLBACK_PLAN)
