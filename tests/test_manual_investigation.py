"""Tests for manual investigation trigger endpoint (POST /api/incidents/{id}/investigate)."""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.database import Base, SessionLocal, engine
from app.main import app
from app.models import Incident


@pytest.fixture(scope="function", autouse=True)
def setup_database():
    """Create fresh tables for each test."""
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def client():
    return TestClient(app)


def _create_incident(status: str, fp_score: int) -> int:
    """Helper to create an incident with given status and score."""
    db = SessionLocal()
    try:
        incident = Incident(
            resource_name="test-resource",
            signal_type="TestSignal",
            severity="medium",
            source="test_source",
            status=status,
            fp_score=fp_score,
            fp_decision_reason=f"test reason: score={fp_score}",
            timeline=[{"signal": "TestSignal", "source": "test_source"}],
        )
        db.add(incident)
        db.commit()
        db.refresh(incident)
        return incident.id
    finally:
        db.close()


def test_trigger_queued_incident(client):
    """Manually triggering a queued incident changes status to investigating."""
    incident_id = _create_incident(status="queued", fp_score=60)

    with patch("app.routers.incidents.event_queue.push") as mock_push:
        response = client.post(f"/api/incidents/{incident_id}/investigate")

    assert response.status_code == 200
    data = response.json()
    assert data["id"] == incident_id
    assert data["status"] == "investigating"
    assert data["manually_triggered_at"] is not None
    # Verify it's a valid ISO timestamp string
    assert isinstance(data["manually_triggered_at"], str)
    assert len(data["manually_triggered_at"]) > 0

    # Verify queue push was called
    mock_push.assert_called_once_with("signals", {"incident_id": incident_id})


def test_trigger_parked_incident(client):
    """Can also trigger parked incidents (score < 40)."""
    incident_id = _create_incident(status="parked", fp_score=25)

    with patch("app.routers.incidents.event_queue.push") as mock_push:
        response = client.post(f"/api/incidents/{incident_id}/investigate")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "investigating"
    assert data["manually_triggered_at"] is not None
    mock_push.assert_called_once()


def test_trigger_already_investigating(client):
    """Returns 409 if already investigating."""
    incident_id = _create_incident(status="investigating", fp_score=85)

    response = client.post(f"/api/incidents/{incident_id}/investigate")

    assert response.status_code == 409
    assert "already investigating" in response.json()["detail"].lower()


def test_trigger_already_analyzing(client):
    """Returns 409 if currently being analyzed."""
    incident_id = _create_incident(status="analyzing", fp_score=85)

    response = client.post(f"/api/incidents/{incident_id}/investigate")

    assert response.status_code == 409
    assert "already analyzing" in response.json()["detail"].lower()


def test_trigger_already_analyzed(client):
    """Returns 409 if investigation already complete."""
    incident_id = _create_incident(status="analyzed", fp_score=85)

    response = client.post(f"/api/incidents/{incident_id}/investigate")

    assert response.status_code == 409
    assert "already analyzed" in response.json()["detail"].lower()


def test_trigger_failed_incident(client):
    """Returns 409 if incident investigation failed previously."""
    incident_id = _create_incident(status="failed", fp_score=85)

    response = client.post(f"/api/incidents/{incident_id}/investigate")

    assert response.status_code == 409
    assert "already failed" in response.json()["detail"].lower()


def test_trigger_nonexistent_incident(client):
    """Returns 404 for unknown incident ID."""
    response = client.post("/api/incidents/99999/investigate")

    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


def test_trigger_pushes_to_queue(client):
    """Verify event is pushed to queue for worker consumption."""
    incident_id = _create_incident(status="queued", fp_score=60)

    with patch("app.routers.incidents.event_queue.push") as mock_push:
        response = client.post(f"/api/incidents/{incident_id}/investigate")

    assert response.status_code == 200
    # Verify push was called with correct channel and payload
    mock_push.assert_called_once_with("signals", {"incident_id": incident_id})


def test_trigger_idempotent_behavior(client):
    """Calling twice on same queued incident - second call gets 409."""
    incident_id = _create_incident(status="queued", fp_score=60)

    with patch("app.routers.incidents.event_queue.push") as mock_push:
        # First call succeeds
        response1 = client.post(f"/api/incidents/{incident_id}/investigate")
        assert response1.status_code == 200
        assert response1.json()["status"] == "investigating"

        # Second call gets 409 (already investigating)
        response2 = client.post(f"/api/incidents/{incident_id}/investigate")
        assert response2.status_code == 409
        assert "already investigating" in response2.json()["detail"].lower()

        # Queue push only called once
        assert mock_push.call_count == 1


def test_trigger_preserves_other_fields(client):
    """Triggering investigation doesn't modify other incident fields."""
    incident_id = _create_incident(status="queued", fp_score=60)

    with patch("app.routers.incidents.event_queue.push"):
        response = client.post(f"/api/incidents/{incident_id}/investigate")

    assert response.status_code == 200
    data = response.json()

    # All original fields preserved
    assert data["resource_name"] == "test-resource"
    assert data["signal_type"] == "TestSignal"
    assert data["severity"] == "medium"
    assert data["source"] == "test_source"
    assert data["fp_score"] == 60
    assert data["fp_decision_reason"] == "test reason: score=60"
