import threading
from collections import defaultdict
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app import correlation, event_queue, fp_gate
from app.database import get_db
from app.schemas import IncidentOut, SignalIn

router = APIRouter()

# Serialize the read-correlate-create-commit section per resource. FastAPI runs
# these sync handlers in a threadpool, so without this two near-simultaneous
# signals for the same resource can both miss the correlation window and create
# duplicate incidents. Per-resource (not global) so unrelated resources don't
# contend. A multi-process deploy would additionally want a DB unique/partial
# constraint or a Postgres advisory lock — this process-local lock covers the
# single-worker POC only (noted for Day 7).
_resource_locks: dict[str, threading.Lock] = defaultdict(threading.Lock)
_locks_guard = threading.Lock()


def _lock_for(resource_name: str) -> threading.Lock:
    with _locks_guard:
        return _resource_locks[resource_name]


@router.post("/api/signals", response_model=IncidentOut, status_code=status.HTTP_201_CREATED)
def create_signal(signal: SignalIn, db: Session = Depends(get_db)):
    ts = signal.timestamp or datetime.now(timezone.utc)

    with _lock_for(signal.resource_name):
        incident = correlation.find_correlatable_incident(db, signal.resource_name, ts)
        if incident is not None:
            correlation.merge_signal(incident, signal, ts)
        else:
            incident = correlation.new_incident(signal, ts)
            db.add(incident)

        # False-Positive Gate runs before anything touches an LLM — every time
        # correlation changes the incident's shape, re-score it.
        fp_gate.apply(incident)

        db.commit()
        db.refresh(incident)

        if incident.status == "investigating":
            # Hand off to the LangGraph orchestrator. Re-pushing on every
            # additional correlated signal is now deduped worker-side by
            # analyzed_at_count, so it never re-runs the LLM pipeline needlessly.
            event_queue.push("signals", {"incident_id": incident.id})

    return incident
