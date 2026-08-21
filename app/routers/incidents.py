from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import event_queue
from app.database import get_db
from app.models import Incident, utcnow
from app.report import build_report
from app.schemas import IncidentOut

router = APIRouter()

# Rough, deliberately conservative estimate of the LLM work one full
# investigation costs: the planner loop (~2-3 calls) + Root Cause + Risk
# narrative + Remediation. A parked/queued incident makes ZERO of these — that
# is the whole point of the deterministic gate, and this constant is what turns
# "N alerts gated" into a spend-avoided number for the dashboard. Kept low so
# the headline figure is defensible rather than inflated.
_AVG_LLM_CALLS_PER_INVESTIGATION = 6
# Ballpark blended cost of one Claude-class call at this prompt size, in USD.
_EST_COST_PER_LLM_CALL_USD = 0.01

# Statuses that mean the incident was handed to the LLM pipeline (vs. gated
# before any inference).
_LLM_STATUSES = ("investigating", "analyzing", "analyzed", "failed")
# Statuses set by the FP gate that stop an incident BEFORE any LLM spend.
_GATED_STATUSES = ("parked", "queued")


@router.get("/api/incidents", response_model=list[IncidentOut])
def list_incidents(
    db: Session = Depends(get_db),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    """Newest first. Paginated so a long-running instance doesn't return the
    entire table on every dashboard poll — the frontend's default page is the
    first 100."""
    rows = (
        db.execute(
            select(Incident)
            .order_by(Incident.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        .scalars()
        .all()
    )
    return rows


@router.get("/api/stats")
def stats(db: Session = Depends(get_db)):
    """Fleet-level triage stats for the dashboard header.

    The headline the demo leans on: how many alerts the deterministic FP gate
    stopped *before* any LLM was invoked, and the inference spend that avoided.
    `alerts_gated_pre_llm` and the per-status counts are exact; the cost figure
    is an explicit estimate and ships its own assumptions so it can't be
    mistaken for a metered number.
    """
    rows = db.execute(
        select(Incident.status, func.count()).group_by(Incident.status)
    ).all()
    by_status = {status: count for status, count in rows}
    total = sum(by_status.values())

    gated_pre_llm = sum(by_status.get(s, 0) for s in _GATED_STATUSES)
    llm_investigated = sum(by_status.get(s, 0) for s in _LLM_STATUSES)
    llm_calls_avoided = gated_pre_llm * _AVG_LLM_CALLS_PER_INVESTIGATION
    est_cost_saved_usd = round(llm_calls_avoided * _EST_COST_PER_LLM_CALL_USD, 2)

    return {
        "total_alerts": total,
        "alerts_gated_pre_llm": gated_pre_llm,
        "alerts_llm_investigated": llm_investigated,
        "llm_calls_avoided": llm_calls_avoided,
        "est_cost_saved_usd": est_cost_saved_usd,
        "by_status": by_status,
        "assumptions": {
            "avg_llm_calls_per_investigation": _AVG_LLM_CALLS_PER_INVESTIGATION,
            "est_cost_per_llm_call_usd": _EST_COST_PER_LLM_CALL_USD,
        },
    }


@router.get("/api/incidents/{incident_id}", response_model=IncidentOut)
def get_incident(incident_id: int, db: Session = Depends(get_db)):
    incident = db.get(Incident, incident_id)
    if incident is None:
        raise HTTPException(status_code=404, detail="Incident not found")
    return incident


@router.post("/api/incidents/{incident_id}/explain")
def explain_incident(
    incident_id: int,
    force: bool = Query(default=False, description="Regenerate even if a cached explanation exists"),
    db: Session = Depends(get_db),
):
    """On-demand LLM paraphrase of the FP-gate decision.

    This is the ONE place a gated (parked/queued) incident may cost inference,
    and only because a human explicitly clicked for it — spend scales with
    curiosity, not signal volume. Cached on the incident so repeat clicks are
    free; the deterministic `fp_explanation` remains the zero-cost default.
    """
    from app.explain_agent import generate_explanation

    incident = db.get(Incident, incident_id)
    if incident is None:
        raise HTTPException(status_code=404, detail="Incident not found")
    if incident.fp_score is None:
        raise HTTPException(status_code=409, detail="Incident has not been scored by the FP gate yet")

    if incident.llm_explanation and not force:
        return {"explanation": incident.llm_explanation, "cached": True}

    try:
        text = generate_explanation(incident)
    except Exception as exc:
        raise HTTPException(
            status_code=502, detail=f"LLM explanation failed: {type(exc).__name__}: {exc}"
        ) from exc

    incident.llm_explanation = text
    db.commit()
    return {"explanation": text, "cached": False}


@router.get("/api/incidents/{incident_id}/report")
def get_incident_report(incident_id: int, db: Session = Depends(get_db)):
    incident = db.get(Incident, incident_id)
    if incident is None:
        raise HTTPException(status_code=404, detail="Incident not found")

    pdf_bytes = build_report(incident)
    return StreamingResponse(
        iter([pdf_bytes]),
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="incident-{incident_id}-report.pdf"'
        },
    )


@router.post("/api/incidents/{incident_id}/investigate", response_model=IncidentOut)
def trigger_investigation(incident_id: int, db: Session = Depends(get_db)):
    """Manually escalate a gated incident to investigating status.

    Allows operators to override the FP gate and trigger investigation for
    parked/queued incidents. The incident is pushed to the event queue exactly
    as if it had auto-escalated. Returns 409 if already investigating/analyzing/
    analyzed/failed.
    """
    incident = db.get(Incident, incident_id)
    if incident is None:
        raise HTTPException(status_code=404, detail="Incident not found")

    if incident.status not in ("parked", "queued"):
        raise HTTPException(
            status_code=409,
            detail=f"Cannot trigger investigation: incident is already {incident.status}",
        )

    # State transition
    incident.status = "investigating"
    incident.manually_triggered_at = utcnow()
    db.commit()

    # Push to queue (same as auto-escalation in signals.py:53)
    event_queue.push("signals", {"incident_id": incident.id})

    db.refresh(incident)
    return incident
