"""Integration tests for signal intake API with enhanced schema.

Tests that the POST /api/signals endpoint correctly handles both old (backward
compatible) and new (actor/action/outcome enhanced) signal formats.
"""

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_enhanced_signal_creates_incident_with_actor():
    """New signal format with actor/action/outcome creates incident correctly."""
    response = client.post(
        "/api/signals",
        json={
            "signal_type": "UnauthorizedAPICall",
            "resource_name": "test-resource-enhanced",
            "severity": "high",
            "source": "iam_logs",
            "actor": {"type": "user", "id": "alice@example.com", "ip_address": "203.0.113.100"},
            "action": "delete",
            "outcome": "success",
            "event_time": "2026-08-18T14:00:00Z",
            "details": {},
        },
    )

    assert response.status_code == 201
    data = response.json()
    assert data["timeline"][0]["actor"]["type"] == "user"
    assert data["timeline"][0]["actor"]["id"] == "alice@example.com"
    assert data["timeline"][0]["action"] == "delete"
    assert data["timeline"][0]["outcome"] == "success"
    assert data["fp_score"] is not None


def test_legacy_signal_backward_compatible():
    """Old signal format (no actor/action/outcome) still works."""
    response = client.post(
        "/api/signals",
        json={
            "signal_type": "LargeDataUpload",
            "resource_name": "test-resource-legacy",
            "severity": "medium",
            "source": "kubernetes",
            "details": {"size_gb": 1.5},
        },
    )

    assert response.status_code == 201
    data = response.json()
    assert data["timeline"][0].get("actor") is None
    assert data["timeline"][0]["action"] == "other"  # Default
    assert data["timeline"][0].get("outcome") is None
    assert data["fp_score"] is not None


def test_blocked_outcome_reduces_score():
    """Blocked outcome with service actor should reduce FP score."""
    response = client.post(
        "/api/signals",
        json={
            "signal_type": "UnauthorizedAPICall",
            "resource_name": "test-blocked",
            "severity": "low",
            "source": "endpoint_agent",
            "actor": {"type": "service", "id": "test-svc"},
            "action": "read",
            "outcome": "blocked",
            "details": {},
        },
    )

    assert response.status_code == 201
    data = response.json()
    # With low severity + blocked outcome, should be parked
    # Score: (5 (low) + 10 (div) + 8 (source) + 0 (anomaly) + 8 (actor) - 10 (blocked)) * 0.9 (read) = ~19 -> parked
    assert data["status"] == "parked"


def test_anonymous_actor_with_success_increases_score():
    """Anonymous actor with successful action should increase suspicion."""
    response = client.post(
        "/api/signals",
        json={
            "signal_type": "UnauthorizedAPICall",
            "resource_name": "test-anonymous",
            "severity": "high",
            "source": "azure_monitor",
            "actor": {"type": "anonymous", "id": None, "ip_address": "198.51.100.42"},
            "action": "delete",
            "outcome": "success",
            "details": {},
        },
    )

    assert response.status_code == 201
    data = response.json()
    # High severity + anonymous actor + delete action + success = high score
    # Score: (30 (high) + 10 (div) + 20 (source) + 0 (anomaly) + 2 (anonymous) + 0 (success)) * 1.2 (delete) = 74 -> queued
    assert data["status"] in ["queued", "investigating"]
    assert data["fp_score"] > 60


def test_correlation_preserves_actor_data():
    """Correlated signals should preserve actor data from both signals."""
    resource = "test-correlation-actor"

    # First signal
    response1 = client.post(
        "/api/signals",
        json={
            "signal_type": "PublicStorageBucket",
            "resource_name": resource,
            "severity": "critical",
            "source": "azure_monitor",
            "actor": {"type": "user", "id": "engineer@company.com"},
            "action": "update",
            "outcome": "success",
            "details": {"bucket_acl": "public-read"},
        },
    )
    assert response1.status_code == 201
    incident_id = response1.json()["id"]

    # Second signal (should correlate)
    response2 = client.post(
        "/api/signals",
        json={
            "signal_type": "LargeDataUpload",
            "resource_name": resource,
            "severity": "high",
            "source": "azure_monitor",
            "actor": {"type": "service", "id": "svc-exporter"},
            "action": "create",
            "outcome": "success",
            "details": {"size_gb": 4.2},
        },
    )
    assert response2.status_code == 201
    data = response2.json()

    # Should be same incident (correlated)
    assert data["id"] == incident_id
    assert data["correlated_count"] == 2

    # Timeline should have both actors
    assert len(data["timeline"]) == 2
    assert data["timeline"][0]["actor"]["type"] == "user"
    assert data["timeline"][1]["actor"]["type"] == "service"
