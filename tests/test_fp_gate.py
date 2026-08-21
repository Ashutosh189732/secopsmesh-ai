"""Unit + regression tests for the deterministic False-Positive gate.

Covers the four scoring factors (severity, diversity, source, anomaly), the
input-hardening rules, and a regression matrix that replays every demo scenario
in demo/scenarios/*.json through the gate and asserts the final status is
unchanged from the documented behavior.
"""

import json
from pathlib import Path

import pytest

from app import fp_gate
from app.models import Incident

SCENARIOS_DIR = Path(__file__).resolve().parent.parent / "demo" / "scenarios"


def make_incident(signals: list[dict]) -> Incident:
    """Build an Incident the way correlation.py would after folding in `signals`.

    Severity escalates to the worst signal; timeline carries one entry per
    signal with its own type/source/details (mirrors correlation.merge_signal).
    """
    rank = {"low": 0, "medium": 1, "high": 2, "critical": 3}
    worst = max(signals, key=lambda s: rank.get(s["severity"], 0))["severity"]
    timeline = [
        {
            "signal": s["signal_type"],
            "source": s["source"],
            "details": s.get("details", {}),
            # NEW: Include actor/action/outcome in timeline if present
            "actor": s.get("actor"),
            "action": s.get("action", "other"),
            "outcome": s.get("outcome"),
        }
        for s in signals
    ]
    first = signals[0]
    return Incident(
        resource_name=first["resource_name"],
        signal_type=first["signal_type"],
        severity=worst,
        source=first["source"],
        details=first.get("details", {}),
        timeline=timeline,
        correlated_count=len(signals),
    )


# --- Factor-level unit tests -------------------------------------------------


def test_low_unknown_source_parks():
    inc = make_incident(
        [{"signal_type": "X", "resource_name": "r", "severity": "low", "source": "endpoint_agent"}]
    )
    score, reason = fp_gate.score_incident(inc)
    assert score == 5 + 10 + 8 + 0 == 23
    assert "parked" in reason  # Unicode arrow (→) makes exact match fragile


def test_diversity_rewards_distinct_types_not_repetition():
    same = make_incident(
        [
            {"signal_type": "UnauthorizedAPICall", "resource_name": "r", "severity": "low", "source": "iam_logs"},
            {"signal_type": "UnauthorizedAPICall", "resource_name": "r", "severity": "low", "source": "iam_logs"},
            {"signal_type": "UnauthorizedAPICall", "resource_name": "r", "severity": "low", "source": "iam_logs"},
        ]
    )
    diverse = make_incident(
        [
            {"signal_type": "UnauthorizedAPICall", "resource_name": "r", "severity": "low", "source": "iam_logs"},
            {"signal_type": "LargeDataUpload", "resource_name": "r", "severity": "low", "source": "iam_logs"},
            {"signal_type": "PublicStorageBucket", "resource_name": "r", "severity": "low", "source": "iam_logs"},
        ]
    )
    assert fp_gate._diversity_points(same) == 10  # 1 distinct type
    assert fp_gate._diversity_points(diverse) == 40  # 3 distinct types


def test_anomaly_call_volume_ratio():
    inc = make_incident(
        [
            {
                "signal_type": "UnauthorizedAPICall",
                "resource_name": "r",
                "severity": "critical",
                "source": "iam_logs",
                "details": {"call_count_last_hour": 47, "baseline_call_count_last_hour": 2},
            }
        ]
    )
    # 47/2 = 23.5 -> int 23 -> capped at 15
    assert fp_gate._anomaly_points(inc) == 15


def test_anomaly_needs_both_count_and_baseline():
    inc = make_incident(
        [
            {
                "signal_type": "UnauthorizedAPICall",
                "resource_name": "r",
                "severity": "high",
                "source": "iam_logs",
                "details": {"call_count_last_hour": 12},  # no baseline
            }
        ]
    )
    assert fp_gate._anomaly_points(inc) == 0


def test_anomaly_public_bucket_and_upload():
    bucket = make_incident(
        [{"signal_type": "PublicStorageBucket", "resource_name": "r", "severity": "low",
          "source": "waf_alert", "details": {"bucket_acl": "public-read"}}]
    )
    upload = make_incident(
        [{"signal_type": "LargeDataUpload", "resource_name": "r", "severity": "low",
          "source": "kubernetes", "details": {"size_gb": 8.7}}]
    )
    small = make_incident(
        [{"signal_type": "LargeDataUpload", "resource_name": "r", "severity": "low",
          "source": "kubernetes", "details": {"size_gb": 0.2}}]
    )
    assert fp_gate._anomaly_points(bucket) == 10
    assert fp_gate._anomaly_points(upload) == 5
    assert fp_gate._anomaly_points(small) == 0


def test_malformed_details_never_raise():
    for bad in [None, "not-a-dict", {"size_gb": "huge"}, {"call_count_last_hour": None}]:
        inc = make_incident(
            [{"signal_type": "LargeDataUpload", "resource_name": "r", "severity": "low",
              "source": "kubernetes", "details": bad}]
        )
        assert fp_gate._anomaly_points(inc) == 0


def test_unrecognized_severity_treated_as_medium():
    inc = make_incident(
        [{"signal_type": "X", "resource_name": "r", "severity": "catastrophic", "source": "iam_logs"}]
    )
    pts, unrecognized = fp_gate._severity_points(inc)
    assert pts == fp_gate.SEVERITY_POINTS["medium"] == 15
    assert unrecognized is True


def test_all_sources_trusted_for_severity():
    """All configured sources are trusted to report severity accurately."""
    # Even sources not in SOURCE_RELIABILITY_POINTS get full severity credit
    inc_unknown = make_incident(
        [{"signal_type": "X", "resource_name": "r", "severity": "critical", "source": "some_random_agent"}]
    )
    pts_unknown, _ = fp_gate._severity_points(inc_unknown)
    assert pts_unknown == 40  # No capping

    # Known sources also get full severity credit
    inc_known = make_incident(
        [{"signal_type": "X", "resource_name": "r", "severity": "critical", "source": "iam_logs"}]
    )
    pts_known, _ = fp_gate._severity_points(inc_known)
    assert pts_known == 40


# --- Natural-language explanation builder ------------------------------------


def test_explanation_parked_mentions_noise_and_unrecognized_source():
    inc = make_incident(
        [{"signal_type": "X", "resource_name": "r", "severity": "low", "source": "endpoint_agent"}]
    )
    text = fp_gate.build_explanation(inc)
    assert "parked as likely noise" in text
    assert "'endpoint_agent' is not in the high-reliability source list" in text
    assert "no LLM cost" in text


def test_explanation_queued_mentions_missing_baseline():
    inc = make_incident(
        [{"signal_type": "UnauthorizedAPICall", "resource_name": "r", "severity": "high",
          "source": "iam_logs", "details": {"call_count_last_hour": 12}}]
    )
    text = fp_gate.build_explanation(inc)
    assert "queued for human review" in text
    assert "no baseline to compare against" in text


def test_explanation_all_sources_get_full_severity_credit():
    """Even sources not in high-reliability list get full severity credit (no capping)."""
    inc = make_incident(
        [{"signal_type": "X", "resource_name": "r", "severity": "critical", "source": "random_tool"}]
    )
    text = fp_gate.build_explanation(inc)
    # Should mention critical severity contributed 40 pts (not capped)
    assert "Severity 'critical' contributed 40 pts" in text
    # Should mention the source is not in high-reliability list
    assert "not in the high-reliability source list" in text


def test_explanation_investigating_names_fired_anomaly_rules():
    inc = make_incident(
        [
            {"signal_type": "PublicStorageBucket", "resource_name": "r", "severity": "critical",
             "source": "azure_monitor", "details": {"bucket_acl": "public-read"}},
            {"signal_type": "LargeDataUpload", "resource_name": "r", "severity": "high",
             "source": "azure_monitor", "details": {"size_gb": 4.2}},
        ]
    )
    text = fp_gate.build_explanation(inc)
    assert "investigation pipeline" in text
    assert "public-read" in text
    assert "2 distinct signal types" in text


def test_explanation_for_analyzed_incident_shows_detailed_breakdown():
    """Analyzed incidents should still show the detailed FP gate breakdown
    for audit trail purposes, not a generic 'it passed' message."""
    inc = make_incident(
        [
            {"signal_type": "PublicStorageBucket", "resource_name": "r", "severity": "critical",
             "source": "azure_monitor", "details": {"bucket_acl": "public-read"}},
            {"signal_type": "LargeDataUpload", "resource_name": "r", "severity": "high",
             "source": "azure_monitor", "details": {"size_gb": 4.2}},
        ]
    )
    fp_gate.apply(inc)
    assert inc.status == "investigating"

    # Simulate the orchestrator moving the incident to analyzing
    inc.status = "analyzing"
    text = fp_gate.build_explanation(inc)
    # Should show detailed breakdown, not generic summary
    assert "investigation pipeline" in text
    assert "Severity 'critical' contributed" in text
    assert "distinct signal types" in text
    # Should NOT contain the generic message anymore
    assert "full investigation results appear below" not in text

    # Same for analyzed status
    inc.status = "analyzed"
    text = fp_gate.build_explanation(inc)
    assert "investigation pipeline" in text
    assert "Severity 'critical' contributed" in text
    assert "distinct signal types" in text
    assert "full investigation results appear below" not in text


def test_explanation_matches_apply_decision_for_all_scenarios():
    # The explanation derives its decision from the score — it must never
    # disagree with what apply() would set.
    for path in _load_scenarios():
        scenario = json.loads(path.read_text(encoding="utf-8"))
        for i in range(1, len(scenario["signals"]) + 1):
            inc = make_incident(scenario["signals"][:i])
            fp_gate.apply(inc)
            text = fp_gate.build_explanation(inc)
            expected_phrase = {
                "parked": "parked as likely noise",
                "queued": "queued for human review",
                "investigating": "investigation pipeline",
            }[inc.status]
            assert expected_phrase in text, f"{path.stem} after {i} signals: {text}"


# --- Regression matrix: every demo scenario keeps its documented status ------

# Final status after all of a scenario's signals have been folded in.
EXPECTED_FINAL_STATUS = {
    "01_parked": "parked",
    "02_queued": "queued",
    "03_investigating_gdpr": "investigating",
    "04_investigating_access_control": "investigating",
    "05_severity_escalation": "investigating",
    "06_kubernetes_anchored": "investigating",
    "07_noise_batch": "parked",  # three independent incidents, all parked
    "08_presenter_paced_escalation": "investigating",
}


def _load_scenarios():
    return sorted(SCENARIOS_DIR.glob("*.json"))


@pytest.mark.parametrize("path", _load_scenarios(), ids=lambda p: p.stem)
def test_scenario_final_status_unchanged(path):
    scenario = json.loads(path.read_text(encoding="utf-8"))
    signals = scenario["signals"]
    expected = EXPECTED_FINAL_STATUS[path.stem]

    if path.stem == "07_noise_batch":
        # Different resource_names -> each stays its own single-signal incident.
        for sig in signals:
            inc = make_incident([sig])
            fp_gate.apply(inc)
            assert inc.status == "parked", f"{sig['resource_name']}: {inc.fp_decision_reason}"
        return

    # Same resource_name -> signals correlate into one incident; score after
    # each successive signal has folded in, assert the final one matches.
    inc = make_incident(signals)
    fp_gate.apply(inc)
    assert inc.status == expected, inc.fp_decision_reason


# --- Actor/Action/Outcome scoring tests (Phase 1 enhancements) ---------------


def test_actor_trust_system_highest():
    """System actors get highest trust score (10 points)."""
    inc = make_incident(
        [
            {
                "signal_type": "UnauthorizedAPICall",
                "resource_name": "test-resource",
                "severity": "low",
                "source": "iam_logs",
                "details": {},
                "actor": {"type": "system", "id": "kernel-process"},
                "action": "execute",
                "outcome": "success",
            }
        ]
    )
    assert fp_gate._actor_trust_points(inc) == 10


def test_actor_trust_anonymous_lowest():
    """Anonymous actors get lowest trust (2 points)."""
    inc = make_incident(
        [
            {
                "signal_type": "UnauthorizedAPICall",
                "resource_name": "test-resource",
                "severity": "low",
                "source": "iam_logs",
                "details": {},
                "actor": {"type": "anonymous", "id": None},
                "action": "read",
                "outcome": "success",
            }
        ]
    )
    assert fp_gate._actor_trust_points(inc) == 2


def test_outcome_blocked_reduces_score():
    """Blocked outcome reduces score by -10 points."""
    blocked_inc = make_incident(
        [
            {
                "signal_type": "UnauthorizedAPICall",
                "resource_name": "test-resource",
                "severity": "critical",
                "source": "azure_monitor",
                "details": {},
                "actor": {"type": "user", "id": "test@test.com"},
                "action": "delete",
                "outcome": "blocked",
            }
        ]
    )

    success_inc = make_incident(
        [
            {
                "signal_type": "UnauthorizedAPICall",
                "resource_name": "test-resource",
                "severity": "critical",
                "source": "azure_monitor",
                "details": {},
                "actor": {"type": "user", "id": "test@test.com"},
                "action": "delete",
                "outcome": "success",
            }
        ]
    )

    blocked_score = fp_gate.score_incident(blocked_inc)[0]
    success_score = fp_gate.score_incident(success_inc)[0]
    assert blocked_score < success_score


def test_action_delete_multiplier_boosts_score():
    """Delete action applies 1.2x risk multiplier."""
    delete_inc = make_incident(
        [
            {
                "signal_type": "UnauthorizedAPICall",
                "resource_name": "test-resource",
                "severity": "high",
                "source": "iam_logs",
                "details": {},
                "actor": {"type": "user", "id": "test@test.com"},
                "action": "delete",
                "outcome": "success",
            }
        ]
    )

    read_inc = make_incident(
        [
            {
                "signal_type": "UnauthorizedAPICall",
                "resource_name": "test-resource",
                "severity": "high",
                "source": "iam_logs",
                "details": {},
                "actor": {"type": "user", "id": "test@test.com"},
                "action": "read",
                "outcome": "success",
            }
        ]
    )

    assert fp_gate.score_incident(delete_inc)[0] > fp_gate.score_incident(read_inc)[0]


def test_backward_compat_missing_actor_fields():
    """Old signals without actor/action/outcome still score correctly."""
    # Old format: no actor/action/outcome
    inc = make_incident(
        [
            {
                "signal_type": "PublicStorageBucket",
                "resource_name": "test-resource",
                "severity": "critical",
                "source": "azure_monitor",
                "details": {"bucket_acl": "public-read"},
            }
        ]
    )

    score, reason = fp_gate.score_incident(inc)
    # Score should be: 40 (sev) + 10 (div=1) + 20 (source) + 10 (anomaly) + 0 (actor) + 0 (outcome) * 1.0 (action) = 80
    assert score == 80
    assert "actor_trust(0)" in reason
    assert "outcome_adj(0)" in reason
