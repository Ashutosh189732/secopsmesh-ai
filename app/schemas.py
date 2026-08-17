from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


# The signal types this POC's connector routing and demo scenario know about.
# NOT a closed set: `signal_type` on the wire is a free string (see SignalIn),
# so a monitoring tool emitting a detection we haven't catalogued is still
# accepted and investigated — connector routing falls back to a default order
# for unknown types (see connectors.connector_order_for) — rather than rejected
# with a 422. Dropping a real alert on a schema mismatch is worse than letting
# the FP gate score it. Kept as a constant so the demo's canonical vocabulary
# stays discoverable.
KNOWN_SIGNAL_TYPES = ("PublicStorageBucket", "LargeDataUpload", "UnauthorizedAPICall")


class Severity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class SignalIn(BaseModel):
    signal_type: str = Field(..., min_length=1)
    resource_name: str = Field(..., min_length=1)
    severity: Severity
    source: str = Field(..., min_length=1)
    timestamp: datetime | None = None
    details: dict = Field(default_factory=dict)


class IncidentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    resource_name: str
    signal_type: str
    severity: str
    source: str
    status: str
    details: dict
    timeline: list
    correlated_count: int
    fp_score: int | None
    fp_decision_reason: str | None
    # Deterministic template explanation (model @property, zero LLM cost) and
    # the on-demand LLM paraphrase (null until a user requests one).
    fp_explanation: str | None = None
    llm_explanation: str | None = None
    evidence: list
    evidence_guard_triggered: bool
    policies: list
    root_cause: dict | None
    risk_assessment: dict | None
    remediation_plan: dict | None
    analyzed_at_count: int | None
    created_at: datetime
    updated_at: datetime
