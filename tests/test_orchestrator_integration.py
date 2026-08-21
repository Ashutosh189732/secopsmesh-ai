"""Integration tests for improved orchestrator prompts.

These tests verify that the enhanced prompt guidance is correctly applied
and that context payloads include all necessary information for smart
connector selection.
"""

import pytest
from app import config
from app.orchestrator.graph import (
    _build_planner_prompt,
    _build_context_payload,
)


@pytest.fixture
def enable_agentic_mode():
    """Temporarily enable agentic mode for tests."""
    original = config.settings.use_agentic_connector_selection
    config.settings.use_agentic_connector_selection = True
    yield
    config.settings.use_agentic_connector_selection = original


@pytest.fixture
def disable_agentic_mode():
    """Temporarily disable agentic mode for tests."""
    original = config.settings.use_agentic_connector_selection
    config.settings.use_agentic_connector_selection = False
    yield
    config.settings.use_agentic_connector_selection = original


def test_agentic_prompt_includes_signal_type_guidance():
    """Verify agentic mode prompt includes signal type → connector mapping."""
    prompt = _build_planner_prompt(agentic_mode=True)

    # Should include signal type guidance section
    assert "SIGNAL TYPE → CONNECTOR GUIDANCE" in prompt

    # Should include specific guidance for each signal type
    assert "PublicStorageBucket:" in prompt
    assert "UnauthorizedAPICall:" in prompt
    assert "LargeDataUpload:" in prompt

    # Should explain priorities
    assert "azure_monitor: Config changes that exposed storage" in prompt
    assert "iam_logs: Auth attempts, API call patterns" in prompt
    assert "kubernetes: Pod logs, volume writes" in prompt


def test_agentic_prompt_includes_evidence_diversity_guidance():
    """Verify agentic mode prompt includes evidence diversity guidance."""
    prompt = _build_planner_prompt(agentic_mode=True)

    assert "EVIDENCE DIVERSITY" in prompt
    assert "different TYPES of evidence" in prompt
    assert "deployment logs + runtime behavior + code changes + access patterns" in prompt


def test_agentic_prompt_includes_context_driven_selection():
    """Verify agentic mode prompt includes context-driven selection rules."""
    prompt = _build_planner_prompt(agentic_mode=True)

    assert "CONTEXT-DRIVEN SELECTION" in prompt
    assert "keyvault" in prompt.lower()
    assert "secrets" in prompt.lower()
    assert "iam_logs priority" in prompt


def test_agentic_prompt_includes_confidence_guidance():
    """Verify agentic mode prompt includes enhanced confidence guidance."""
    prompt = _build_planner_prompt(agentic_mode=True)

    assert "CONFIDENCE GUIDANCE" in prompt
    assert "EQUALLY relevant" in prompt
    assert "MORE relevant" in prompt
    # Should explain when lower confidence wins over higher confidence
    assert "iam_logs (0.80) beats azure_monitor (0.95)" in prompt


def test_hard_coded_prompt_excludes_agentic_guidance():
    """Verify hard-coded mode prompt does NOT include agentic guidance."""
    prompt = _build_planner_prompt(agentic_mode=False)

    # Should NOT include agentic-specific sections
    assert "SIGNAL TYPE → CONNECTOR GUIDANCE" not in prompt
    assert "EVIDENCE DIVERSITY" not in prompt
    assert "CONTEXT-DRIVEN SELECTION" not in prompt
    assert "CONFIDENCE GUIDANCE" not in prompt

    # Should still have basic instructions
    assert "evidence-gathering planner" in prompt
    assert "SOC incident investigation" in prompt


def test_context_payload_includes_incident_details_for_keyvault():
    """Verify context payload includes API details for keyvault incidents."""
    payload = _build_context_payload(
        signal_type="UnauthorizedAPICall",
        resource_name="prod-keyvault",
        severity="high",
        details={
            "api": "azure.keyvault.secrets.list",
            "caller": "svc-backup",
            "call_count_last_hour": 47,
            "baseline_call_count_last_hour": 2,
        },
        timeline=[],
        evidence=[],
        remaining_connectors=["iam_logs", "azure_monitor"],
    )

    # Should include the API name to guide connector selection
    assert "azure.keyvault.secrets.list" in payload
    assert "call_count_last_hour" in payload
    assert "47" in payload
    # Guidance says keyvault → iam_logs priority, so LLM needs this context
    assert "INCIDENT DETAILS" in payload


def test_context_payload_includes_timeline_for_diversity():
    """Verify context payload includes timeline sources for diversity guidance."""
    timeline = [
        {
            "signal_type": "LargeDataUpload",
            "source": "kubernetes",
            "actor": {"type": "service", "id": "ml-trainer"},
            "action": "create",
            "outcome": "success",
            "event_time": "2026-08-15T10:00:00Z",
        },
        {
            "signal_type": "UnauthorizedAPICall",
            "source": "azure_monitor",
            "actor": {"type": "service", "id": "ml-trainer"},
            "action": "access",
            "outcome": "success",
            "event_time": "2026-08-15T10:05:00Z",
        },
    ]

    payload = _build_context_payload(
        signal_type="LargeDataUpload",
        resource_name="ml-training-cluster",
        severity="high",
        details={"size_gb": 8.7},
        timeline=timeline,
        evidence=[],
        remaining_connectors=["kubernetes", "azure_monitor", "github_commits"],
    )

    # Should show timeline
    assert "TIMELINE (2 events)" in payload

    # Should explicitly list sources to guide diversity
    assert "Timeline includes signals from:" in payload
    # Both sources should be mentioned
    assert "kubernetes" in payload
    assert "azure_monitor" in payload


def test_context_payload_storage_incident_includes_acl():
    """Verify storage incidents include bucket ACL details."""
    payload = _build_context_payload(
        signal_type="PublicStorageBucket",
        resource_name="prod-analytics-exports",
        severity="critical",
        details={"bucket_acl": "public-read", "allow_blob_public_access": True},
        timeline=[],
        evidence=[],
        remaining_connectors=["azure_monitor", "github_commits", "iam_logs"],
    )

    # Should include storage-specific details to guide connector choice
    assert "bucket_acl" in payload
    assert "public-read" in payload
    # Guidance says storage → azure_monitor + github_commits, so LLM needs ACL context


def test_context_payload_includes_evidence_already_collected():
    """Verify context payload shows evidence already collected."""
    evidence = [
        {
            "connector": "azure_monitor",
            "confidence": 0.95,
            "data": {"deployment_id": "rel-123", "change": "bucket ACL opened"},
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

    # Should show what evidence was already collected
    assert "EVIDENCE COLLECTED SO FAR (1 items)" in payload
    assert "azure_monitor" in payload
    assert "deployment_id" in payload
    # LLM can see azure_monitor already queried, can choose diverse next connector


def test_context_payload_timeline_truncated_to_5():
    """Verify timeline is limited to 5 most recent events to avoid token bloat."""
    long_timeline = [
        {
            "signal_type": "UnauthorizedAPICall",
            "source": f"source_{i}",
            "index": i,
            "event_time": f"2026-08-15T{10+i:02d}:00:00Z",
        }
        for i in range(10)
    ]

    payload = _build_context_payload(
        signal_type="UnauthorizedAPICall",
        resource_name="test-resource",
        severity="medium",
        details={},
        timeline=long_timeline,
        evidence=[],
        remaining_connectors=["iam_logs"],
    )

    # Should only include last 5
    assert "TIMELINE (5 events)" in payload
    # Indices 5-9 should be present
    assert '"index": 9' in payload
    # Indices 0-4 should NOT be present
    assert '"index": 0' not in payload


def test_agentic_mode_fixture_enables_flag(enable_agentic_mode):
    """Verify fixture correctly enables agentic mode."""
    assert config.settings.use_agentic_connector_selection is True


def test_hard_coded_mode_fixture_disables_flag(disable_agentic_mode):
    """Verify fixture correctly disables agentic mode."""
    assert config.settings.use_agentic_connector_selection is False
