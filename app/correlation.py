"""Correlation Engine — Day 2.

Groups signals for the same resource within a 10-minute window into a single
incident. Pure Python, no LLM — alert correlation is a solved deterministic
problem; using a model here would just add cost and hallucination risk.

The window is anchored to the candidate incident's `created_at` (the first
signal that started it), not a sliding window off the most recent signal —
simplest interpretation that keeps incidents bounded in size.
"""

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Incident
from app.schemas import SignalIn

CORRELATION_WINDOW = timedelta(minutes=10)

_SEVERITY_RANK = {"low": 0, "medium": 1, "high": 2, "critical": 3}


def _more_severe(a: str, b: str) -> str:
    return a if _SEVERITY_RANK.get(a, 0) >= _SEVERITY_RANK.get(b, 0) else b


def find_correlatable_incident(db: Session, resource_name: str, ts: datetime) -> Incident | None:
    """Most recent open-window incident for this resource, if any."""
    window_start = ts - CORRELATION_WINDOW
    return (
        db.execute(
            select(Incident)
            .where(Incident.resource_name == resource_name)
            .where(Incident.created_at >= window_start)
            .order_by(Incident.created_at.desc())
        )
        .scalars()
        .first()
    )


def merge_signal(incident: Incident, signal: SignalIn, ts: datetime) -> None:
    """Fold a correlated signal into an existing incident, in place.

    Reassigns `timeline` (rather than `.append`-ing) so SQLAlchemy's change
    tracking picks up the mutation on a plain JSON column.
    """
    incident.timeline = [
        *incident.timeline,
        {
            "signal": signal.signal_type,
            "timestamp": ts.isoformat(),
            "source": signal.source,
            # Keep each correlated signal's type-specific fields (upload size,
            # caller identity, API name, ...). Without this only the first
            # signal's details survive on the incident, so the downstream
            # Root Cause / Policy agents never see the later signals' payloads.
            "details": signal.details,
            # NEW: Store actor/action/outcome in timeline
            "actor": signal.actor.model_dump() if signal.actor else None,
            "action": signal.action.value,
            "outcome": signal.outcome.value if signal.outcome else None,
            "event_time": signal.event_time.isoformat() if signal.event_time else None,
            # AI-generated summary (from demo scenarios) or None
            "summary": signal.details.get("summary") if isinstance(signal.details, dict) else None,
        },
    ]
    incident.correlated_count += 1
    incident.severity = _more_severe(incident.severity, signal.severity.value)


def new_incident(signal: SignalIn, ts: datetime) -> Incident:
    """Build a fresh incident from a signal that didn't correlate to anything."""
    return Incident(
        resource_name=signal.resource_name,
        signal_type=signal.signal_type,
        severity=signal.severity.value,
        source=signal.source,
        status="new",
        details=signal.details,
        timeline=[
            {
                "signal": signal.signal_type,
                "timestamp": ts.isoformat(),
                "source": signal.source,
                "details": signal.details,
                # NEW: Include actor/action/outcome in first timeline entry
                "actor": signal.actor.model_dump() if signal.actor else None,
                "action": signal.action.value,
                "outcome": signal.outcome.value if signal.outcome else None,
                "event_time": signal.event_time.isoformat() if signal.event_time else None,
                # AI-generated summary (from demo scenarios) or None
                "summary": signal.details.get("summary") if isinstance(signal.details, dict) else None,
            }
        ],
        correlated_count=1,
    )
