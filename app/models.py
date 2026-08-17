from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Incident(Base):
    __tablename__ = "incidents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    resource_name: Mapped[str] = mapped_column(String, index=True)
    signal_type: Mapped[str] = mapped_column(String)
    severity: Mapped[str] = mapped_column(String)
    source: Mapped[str] = mapped_column(String)
    # Lifecycle: new -> parked | queued | investigating (set by the FP gate),
    # then investigating -> analyzing -> analyzed (or failed) as the background
    # orchestrator picks the incident up and finishes. A terminal `analyzed`
    # lets the dashboard tell "investigation running" from "investigation done"
    # — both used to sit on `investigating` forever.
    status: Mapped[str] = mapped_column(String, default="new")

    # Raw type-specific fields from the incoming signal (bucket name, upload
    # size, caller identity, etc.) — kept as-is for later evidence/correlation use.
    details: Mapped[dict] = mapped_column(JSON, default=dict)

    # Chronological event list this incident has accumulated. Day 1 seeds it
    # with the triggering signal; Day 2's correlation engine appends to it
    # when merging related signals for the same resource.
    timeline: Mapped[list] = mapped_column(JSON, default=list)
    correlated_count: Mapped[int] = mapped_column(Integer, default=1)

    # Set by the Day 2 False-Positive Gate every time correlation changes.
    # fp_decision_reason is a human-readable breakdown of the score, shown
    # prominently in the Day 6 dashboard.
    fp_score: Mapped[int | None] = mapped_column(Integer, default=None)
    fp_decision_reason: Mapped[str | None] = mapped_column(String, default=None)

    # On-demand LLM paraphrase of the gate decision (POST /api/incidents/{id}/
    # explain). Persisted so repeat clicks return the cached text instead of
    # re-spending inference. None until a user explicitly asks.
    llm_explanation: Mapped[str | None] = mapped_column(String, default=None)

    @property
    def fp_explanation(self) -> str | None:
        """Deterministic natural-language explanation of the gate decision.

        Computed on read (not stored) so it always reflects the incident's
        current shape and the current rule wording — including incidents
        created before this property existed. Zero LLM cost by construction.
        """
        if self.fp_score is None:
            return None
        from app import fp_gate  # local import — fp_gate imports this module

        return fp_gate.build_explanation(self)

    # Populated by the Day 3 LangGraph orchestrator's Evidence Agent. Each
    # item carries {connector, source, confidence, fetched_at, data} — the
    # Evidence Trust Layer. guard_triggered is True if the 90s run-time cap
    # cut the investigation short before the planner judged evidence "enough".
    evidence: Mapped[list] = mapped_column(JSON, default=list)
    evidence_guard_triggered: Mapped[bool] = mapped_column(Boolean, default=False)

    # Day 4: top-3 policy snippets retrieved by the Policy Agent (RAG over
    # policies/*.md) and the Root Cause Agent's structured, cited conclusion.
    policies: Mapped[list] = mapped_column(JSON, default=list)
    root_cause: Mapped[dict | None] = mapped_column(JSON, default=None)

    # Day 5: deterministic score/severity (always computed) + LLM executive
    # narrative, and a stepwise remediation plan. Every remediation step has
    # requires_human_approval forced True in code — nothing here executes
    # automatically, ever.
    risk_assessment: Mapped[dict | None] = mapped_column(JSON, default=None)
    remediation_plan: Mapped[dict | None] = mapped_column(JSON, default=None)

    # `correlated_count` at the time the orchestrator last completed a full
    # analysis of this incident. The worker skips a re-run when this already
    # equals the current count, so additional signals that don't add new
    # correlation (and duplicate queue pushes) no longer re-run the whole LLM
    # pipeline and overwrite good results with a fallback. A genuinely new
    # correlated signal bumps correlated_count and re-triggers exactly one run.
    analyzed_at_count: Mapped[int | None] = mapped_column(Integer, default=None)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
