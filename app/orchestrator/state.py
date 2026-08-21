"""Graph state for the Day 3 LangGraph orchestrator."""

from typing import TypedDict


class InvestigationState(TypedDict):
    incident_id: int
    resource_name: str
    signal_type: str
    severity: str

    evidence: list[dict]
    connectors_queried: list[str]
    remaining_connectors: list[str]

    iteration: int
    guard_triggered: bool

    # Set by plan_investigation each loop; read by the conditional edges.
    next_action: str  # "fetch" | "enough"
    next_connector: str | None

    # Rich context for scenario-aware evidence generation
    details: dict  # Signal-specific fields (bucket_acl, size_gb, caller, api, etc.)
    timeline: list  # Full correlated event timeline with actors/actions/outcomes

    # Connector selection mode
    agentic_mode: bool  # Whether using agentic connector selection
