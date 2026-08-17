"""Background consumer — pops `investigating` incidents off the event queue
and runs the LangGraph orchestrator for each one.

Runs on a daemon thread started from the FastAPI lifespan (app/main.py) so
the demo needs no separate worker process. Polls the in-process queue with a
short timeout so it can notice the stop event promptly on shutdown.
"""

import json
import logging
import threading

from app.database import SessionLocal
from app.event_queue import pop
from app.models import Incident
from app.orchestrator.graph import run_investigation
from app.policy_agent import retrieve_policies
from app.remediation import plan_remediation
from app.risk_assessment import assess_risk
from app.root_cause import determine_root_cause

logger = logging.getLogger(__name__)

_POLL_TIMEOUT_SECONDS = 1.0


def _incident_summary(incident: Incident) -> str:
    """One-line summary for policy retrieval, built from the whole correlated
    timeline (not just the first signal) so every signal's type and details
    contribute their vocabulary to the RAG query."""
    signals = [
        {"signal": e.get("signal"), "source": e.get("source"), "details": e.get("details", {})}
        for e in incident.timeline
    ]
    signal_types = "/".join(dict.fromkeys(s["signal"] for s in signals if s["signal"])) or incident.signal_type
    return (
        f"{signal_types} incident on resource '{incident.resource_name}' "
        f"(severity={incident.severity}, correlated_signals={incident.correlated_count}). "
        f"Signals: {json.dumps(signals)}"
    )


def _process(incident_id: int) -> None:
    db = SessionLocal()
    try:
        incident = db.get(Incident, incident_id)
        if incident is None:
            logger.warning("orchestrator worker: incident %s not found, skipping", incident_id)
            return

        # Dedupe: skip if this incident was already analyzed at its current
        # correlated_count. Extra queue pushes from additional signals that
        # didn't add new correlation (and duplicate pushes for the same signal)
        # become no-ops instead of re-running the whole LLM pipeline and
        # clobbering good results with a fallback on a transient failure.
        if incident.analyzed_at_count is not None and incident.analyzed_at_count >= incident.correlated_count:
            logger.info(
                "orchestrator worker: incident %s already analyzed at count %s, skipping",
                incident_id,
                incident.correlated_count,
            )
            return

        count_at_start = incident.correlated_count
        incident.status = "analyzing"
        db.commit()

        result = run_investigation(
            incident_id=incident.id,
            resource_name=incident.resource_name,
            signal_type=incident.signal_type,
            severity=incident.severity,
        )

        incident.evidence = result["evidence"]
        incident.evidence_guard_triggered = result["guard_triggered"]

        incident.policies = retrieve_policies(_incident_summary(incident))
        incident.root_cause = determine_root_cause(
            incident.timeline, incident.evidence, incident.policies
        )

        incident.risk_assessment = assess_risk(
            signal_type=incident.signal_type,
            resource_name=incident.resource_name,
            severity=incident.severity,
            correlated_count=incident.correlated_count,
            details=incident.details,
            evidence=incident.evidence,
            root_cause=incident.root_cause,
        )
        incident.remediation_plan = plan_remediation(
            incident.root_cause, incident.risk_assessment, incident.policies
        )

        incident.analyzed_at_count = count_at_start
        incident.status = "analyzed"
        db.commit()
    except Exception:
        logger.exception("orchestrator worker: failed processing incident %s", incident_id)
        db.rollback()
        _mark_failed(incident_id)
    finally:
        db.close()


def _mark_failed(incident_id: int) -> None:
    """Best-effort terminal `failed` status after an unexpected error, on a
    fresh session (the working session was just rolled back)."""
    db = SessionLocal()
    try:
        incident = db.get(Incident, incident_id)
        if incident is not None:
            incident.status = "failed"
            db.commit()
    except Exception:
        logger.exception("orchestrator worker: could not mark incident %s failed", incident_id)
        db.rollback()
    finally:
        db.close()


def run_forever(stop_event: threading.Event) -> None:
    while not stop_event.is_set():
        item = pop("signals", block=True, timeout=_POLL_TIMEOUT_SECONDS)
        if item is None:
            continue
        _process(item["incident_id"])


def start(stop_event: threading.Event) -> threading.Thread:
    thread = threading.Thread(target=run_forever, args=(stop_event,), daemon=True, name="orchestrator-worker")
    thread.start()
    return thread
