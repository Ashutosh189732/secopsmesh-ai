"""Tests for orchestrator prompt improvements."""

import pytest
from app.orchestrator.graph import (
    _extract_relevant_details,
    _summarize_timeline_sources,
    _build_context_payload,
)


def test_extract_relevant_details_public_storage():
    """Test extraction of PublicStorageBucket relevant details."""
    details = {
        "bucket_acl": "public-read",
        "allow_blob_public_access": True,
        "irrelevant_field": "noise",
    }
    result = _extract_relevant_details("PublicStorageBucket", details)
    assert "bucket_acl" in result
    assert "allow_blob_public_access" in result
    assert "irrelevant_field" not in result
    assert result["bucket_acl"] == "public-read"


def test_extract_relevant_details_unauthorized_api():
    """Test extraction of UnauthorizedAPICall relevant details."""
    details = {
        "api": "azure.keyvault.secrets.list",
        "caller": "svc-backup",
        "call_count_last_hour": 47,
        "baseline_call_count_last_hour": 2,
        "noise": "ignore",
    }
    result = _extract_relevant_details("UnauthorizedAPICall", details)
    assert "api" in result
    assert "caller" in result
    assert "call_count_last_hour" in result
    assert "baseline_call_count_last_hour" in result
    assert "noise" not in result


def test_extract_relevant_details_large_data():
    """Test extraction of LargeDataUpload relevant details."""
    details = {
        "size_gb": 8.7,
        "file_name": "training_data.parquet",
        "extra_field": "should be filtered",
    }
    result = _extract_relevant_details("LargeDataUpload", details)
    assert "size_gb" in result
    assert "file_name" in result
    assert "extra_field" not in result
    assert result["size_gb"] == 8.7


def test_extract_relevant_details_unknown_signal_type():
    """Test that unknown signal types return all details."""
    details = {
        "field1": "value1",
        "field2": "value2",
        "field3": "value3",
    }
    result = _extract_relevant_details("UnknownSignalType", details)
    assert result == details


def test_extract_relevant_details_empty():
    """Test extraction with empty details dict."""
    result = _extract_relevant_details("PublicStorageBucket", {})
    assert result == {}


def test_summarize_timeline_sources():
    """Test extraction of unique sources from timeline."""
    timeline = [
        {"source": "kubernetes", "signal_type": "LargeDataUpload"},
        {"source": "azure_monitor", "signal_type": "PublicStorageBucket"},
        {"source": "kubernetes", "signal_type": "UnauthorizedAPICall"},  # duplicate
        {"source": "iam_logs", "signal_type": "UnauthorizedAPICall"},
    ]
    sources = _summarize_timeline_sources(timeline)
    assert sources == {"kubernetes", "azure_monitor", "iam_logs"}


def test_summarize_timeline_sources_empty():
    """Test timeline source extraction with empty timeline."""
    sources = _summarize_timeline_sources([])
    assert sources == set()


def test_summarize_timeline_sources_missing_source():
    """Test timeline source extraction with missing source fields."""
    timeline = [
        {"source": "kubernetes"},
        {"signal_type": "UnauthorizedAPICall"},  # no source field
        {"source": "azure_monitor"},
    ]
    sources = _summarize_timeline_sources(timeline)
    assert sources == {"kubernetes", "azure_monitor"}


def test_build_context_payload_includes_all_sections():
    """Test that context payload includes all expected sections."""
    payload = _build_context_payload(
        signal_type="UnauthorizedAPICall",
        resource_name="test-keyvault",
        severity="high",
        details={"api": "azure.keyvault.secrets.list", "caller": "svc-backup"},
        timeline=[{"source": "iam_logs", "signal_type": "UnauthorizedAPICall"}],
        evidence=[],
        remaining_connectors=["azure_monitor", "github_commits"],
    )

    assert "INCIDENT OVERVIEW" in payload
    assert "Signal Type: UnauthorizedAPICall" in payload
    assert "Resource: test-keyvault" in payload
    assert "Severity: high" in payload
    assert "INCIDENT DETAILS" in payload
    assert "azure.keyvault.secrets.list" in payload
    assert "TIMELINE" in payload
    assert "iam_logs" in payload
    assert "Timeline includes signals from: iam_logs" in payload
    assert "REMAINING CONNECTORS" in payload


def test_build_context_payload_limits_timeline_to_5():
    """Test that timeline is truncated to 5 most recent events."""
    long_timeline = [
        {"source": f"source_{i}", "event": f"event_{i}", "index": i}
        for i in range(10)
    ]
    payload = _build_context_payload(
        signal_type="LargeDataUpload",
        resource_name="test-resource",
        severity="medium",
        details={},
        timeline=long_timeline,
        evidence=[],
        remaining_connectors=["kubernetes"],
    )

    # Should only include last 5 events
    assert "TIMELINE (5 events)" in payload
    # Last 5 are indices 5-9
    assert '"index": 5' in payload
    assert '"index": 9' in payload
    # First 5 (indices 0-4) should be excluded
    assert '"index": 0' not in payload
    assert '"index": 4' not in payload


def test_build_context_payload_with_evidence():
    """Test context payload with evidence already collected."""
    evidence = [
        {
            "connector": "azure_monitor",
            "confidence": 0.95,
            "data": {"deployment_id": "rel-123"}
        }
    ]
    payload = _build_context_payload(
        signal_type="PublicStorageBucket",
        resource_name="prod-bucket",
        severity="critical",
        details={"bucket_acl": "public-read"},
        timeline=[],
        evidence=evidence,
        remaining_connectors=["github_commits", "iam_logs"],
    )

    assert "EVIDENCE COLLECTED SO FAR (1 items)" in payload
    assert "azure_monitor" in payload
    assert "0.95" in payload
    assert "deployment_id" in payload


def test_build_context_payload_minimal():
    """Test context payload with minimal data (no details, timeline, or evidence)."""
    payload = _build_context_payload(
        signal_type="PublicStorageBucket",
        resource_name="test-bucket",
        severity="low",
        details={},
        timeline=[],
        evidence=[],
        remaining_connectors=["azure_monitor", "kubernetes"],
    )

    # Should have overview and remaining connectors, but not other sections
    assert "INCIDENT OVERVIEW" in payload
    assert "Signal Type: PublicStorageBucket" in payload
    assert "REMAINING CONNECTORS" in payload
    assert "INCIDENT DETAILS" not in payload
    assert "TIMELINE" not in payload
    assert "EVIDENCE COLLECTED SO FAR" not in payload
