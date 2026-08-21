"""False-Positive Gate — Day 2 (addresses Gap 1: no FP gate before LLM spend).

Deterministic 0-115 score decides whether an incident is worth investigating
before any LLM is invoked. Four additive factors, all pure Python — no I/O, no
model call — so the flood of noise that dominates a real signal stream is
filtered for free:

    severity (0-40) + diversity (0-40) + source_reliability (0-20) + anomaly (0-15)

The gate deliberately stays deterministic and explainable: every decision emits
a one-line `fp_decision_reason` that fully reconstructs the arithmetic. An LLM
here would defeat the point (it exists to decide *whether* to spend on an LLM)
and would cost/latency-tax every signal including the noise.
"""

import logging

from app.models import Incident

logger = logging.getLogger(__name__)

SEVERITY_POINTS = {"critical": 40, "high": 30, "medium": 15, "low": 5}
# Severity is self-reported by the source. An unrecognized severity string is
# treated as medium (not silently 0 -> auto-parked): a misconfigured or
# attacker-controlled source must not be able to score itself out of the gate.
DEFAULT_SEVERITY = "medium"

# Mirrors the relative ordering of Day 3's evidence-connector confidence
# scores (azure_monitor > kubernetes > github_commits > iam_logs). An unlisted
# source gets a low default rather than failing the request closed.
SOURCE_RELIABILITY_POINTS = {
    "azure_monitor": 20,
    "kubernetes": 18,
    "github_commits": 16,
    "iam_logs": 14,
}
DEFAULT_SOURCE_RELIABILITY_POINTS = 8

# Actor trust: higher trust actors (system processes) are less suspicious than
# anonymous actors or unknown identities
ACTOR_TRUST_POINTS = {
    "system": 10,  # Automated system processes highest trust
    "service": 8,  # Service accounts second
    "user": 5,  # Human users moderate trust baseline
    "anonymous": 2,  # Anonymous actors highly suspicious
    "other": 3,  # Unknown actor types low trust
}

# Outcome penalty: blocked/failed actions are less threatening than successful ones
OUTCOME_ADJUSTMENTS = {
    "success": 0,  # Successful = baseline threat
    "partial": 5,  # Partial success = suspicious (permission failure mid-operation)
    "failure": -5,  # Failed = attacker didn't succeed
    "blocked": -10,  # Blocked by security control = noise, not breach
}

# Action risk multiplier: destructive actions boost score
ACTION_RISK_WEIGHTS = {
    "delete": 1.2,  # Destructive actions 20% boost
    "execute": 1.2,
    "create": 1.1,  # Mutating actions 10% boost
    "update": 1.0,
    "read": 0.9,  # Read-only slightly reduces score
    "access": 1.0,
    "other": 1.0,
}

MAX_ANOMALY_POINTS = 15

PARKED_MAX = 40  # score < 40           -> parked
QUEUED_MAX = 80  # 40 <= score <= 80    -> queued
# score > 80                            -> investigating


def _timeline_entries(incident: Incident) -> list[dict]:
    """The incident's signals as a list of timeline dicts.

    Falls back to a single synthetic entry built from the incident's own
    columns if the timeline is empty (shouldn't happen — correlation always
    seeds it — but scoring must never raise on a malformed row).
    """
    if incident.timeline:
        return incident.timeline
    return [
        {
            "signal": incident.signal_type,
            "source": incident.source,
            "details": incident.details or {},
        }
    ]


def _sources(incident: Incident) -> set[str]:
    return {entry.get("source") for entry in _timeline_entries(incident) if entry.get("source")} or {
        incident.source
    }


def _source_reliability_points(incident: Incident) -> int:
    """Best (highest-trust) source among every signal folded into this incident."""
    return max(
        SOURCE_RELIABILITY_POINTS.get(s, DEFAULT_SOURCE_RELIABILITY_POINTS)
        for s in _sources(incident)
    )


def _severity_points(incident: Incident) -> tuple[int, bool]:
    """Returns (points, was_unrecognized).

    All configured sources are trusted to report severity accurately.
    """
    severity = incident.severity
    unrecognized = severity not in SEVERITY_POINTS
    if unrecognized:
        logger.warning(
            "fp_gate: unrecognized severity %r on incident %s, scoring as %s",
            severity,
            getattr(incident, "id", "?"),
            DEFAULT_SEVERITY,
        )
        severity = DEFAULT_SEVERITY

    points = SEVERITY_POINTS[severity]
    return points, unrecognized


def _distinct_signal_types(incident: Incident) -> int:
    """Count of distinct signal *types* corroborating the incident.

    Diversity, not raw volume: three different signal types (bucket goes
    public + large upload + anomalous API call) is real corroboration; the
    same alert firing three times is not and earns nothing extra.
    """
    types = {entry.get("signal") for entry in _timeline_entries(incident) if entry.get("signal")}
    return len(types) or 1


def _diversity_points(incident: Incident) -> int:
    """1 type = 10pts, 2 = 25pts, 3+ = 40pts (capped)."""
    return min(40, 10 + (_distinct_signal_types(incident) - 1) * 15)


def _as_number(value) -> float | None:
    """Best-effort numeric coercion of a free-form details value; None if it isn't one."""
    if isinstance(value, bool):  # bool is an int subclass — reject explicitly
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None


def _entry_anomaly(entry: dict) -> tuple[int, list[str]]:
    """(points, fired-rule notes) for one signal, from its free-form details.

    Every rule defaults to 0 on a missing or malformed key so a garbage payload
    never raises and never scores negative. The notes feed the natural-language
    explanation so a human can see WHICH rule fired, not just the total.
    """
    details = entry.get("details") or {}
    if not isinstance(details, dict):
        return 0, []

    points = 0
    notes: list[str] = []

    # Call-volume anomaly vs a stated baseline (needs both numbers present).
    count = _as_number(details.get("call_count_last_hour"))
    baseline = _as_number(details.get("baseline_call_count_last_hour"))
    if count is not None and baseline is not None and count > 0:
        ratio = count / max(baseline, 1.0)
        pts = min(MAX_ANOMALY_POINTS, int(ratio))
        if pts:
            points += pts
            notes.append(
                f"call volume of {count:g}/hour is ~{ratio:.0f}x its stated baseline "
                f"of {baseline:g} (+{pts})"
            )

    # A publicly readable bucket is inherently anomalous exposure.
    if details.get("bucket_acl") == "public-read":
        points += 10
        notes.append("the storage ACL is public-read, i.e. exposed to the internet (+10)")

    # A non-trivial data upload.
    if entry.get("signal") == "LargeDataUpload":
        size_gb = _as_number(details.get("size_gb"))
        if size_gb is not None and size_gb >= 1.0:
            points += 5
            notes.append(f"a {size_gb:g} GB data upload is non-trivial in size (+5)")

    return min(MAX_ANOMALY_POINTS, points), notes


def _entry_anomaly_points(entry: dict) -> int:
    return _entry_anomaly(entry)[0]


def _anomaly_points(incident: Incident) -> int:
    """Strongest single-signal anomaly across the incident (max, not sum)."""
    return max((_entry_anomaly_points(e) for e in _timeline_entries(incident)), default=0)


def _anomaly_notes(incident: Incident) -> list[str]:
    """Fired-rule notes from the signal that produced the anomaly score."""
    best_points, best_notes = 0, []
    for entry in _timeline_entries(incident):
        points, notes = _entry_anomaly(entry)
        if points > best_points:
            best_points, best_notes = points, notes
    return best_notes


def _count_without_baseline(incident: Incident) -> bool:
    """True if some signal reported a call count but no baseline to compare to."""
    for entry in _timeline_entries(incident):
        details = entry.get("details") or {}
        if not isinstance(details, dict):
            continue
        if (
            _as_number(details.get("call_count_last_hour")) is not None
            and _as_number(details.get("baseline_call_count_last_hour")) is None
        ):
            return True
    return False


def _actor_trust_points(incident: Incident) -> int:
    """Best (most trusted) actor type across all timeline entries.

    Returns the highest trust score found. If no actor data present, returns 0
    (neither penalizes nor boosts the score).
    """
    best = 0
    for entry in _timeline_entries(incident):
        actor_data = entry.get("actor")
        if not actor_data:
            continue
        actor_type = actor_data.get("type", "other")
        best = max(best, ACTOR_TRUST_POINTS.get(actor_type, 0))
    return best


def _outcome_adjustment(incident: Incident) -> int:
    """Worst (most suspicious) outcome across timeline.

    Returns the outcome adjustment with highest absolute value. Negative values
    reduce score (blocked/failed), positive increases (partial success).
    """
    worst_adj = 0
    for entry in _timeline_entries(incident):
        outcome = entry.get("outcome")
        if not outcome:
            continue
        adj = OUTCOME_ADJUSTMENTS.get(outcome, 0)
        if abs(adj) > abs(worst_adj):
            worst_adj = adj
    return worst_adj


def _action_risk_multiplier(incident: Incident) -> float:
    """Highest-risk action multiplier across timeline.

    Returns the maximum risk weight found (1.0+ for destructive actions,
    0.9 for read-only).
    """
    highest = 1.0
    for entry in _timeline_entries(incident):
        action = entry.get("action", "other")
        highest = max(highest, ACTION_RISK_WEIGHTS.get(action, 1.0))
    return highest


def score_incident(incident: Incident) -> tuple[int, str]:
    """Score an incident 0-130 range (enhanced with actor/action/outcome).

    Base scoring (0-115): severity + diversity + source + anomaly
    Then: apply action risk multiplier to base (0.9x-1.2x)
    Finally: add actor trust (+0-10) and outcome adjustment (-10 to +5)

    Returns (score, reason) where reason is the full arithmetic breakdown.
    """
    # Existing factors (unchanged calculation)
    severity_pts, severity_unrecognized = _severity_points(incident)
    diversity_pts = _diversity_points(incident)
    source_pts = _source_reliability_points(incident)
    anomaly_pts = _anomaly_points(incident)

    base_score = severity_pts + diversity_pts + source_pts + anomaly_pts

    # NEW: Actor/outcome/action factors
    actor_pts = _actor_trust_points(incident)
    outcome_adj = _outcome_adjustment(incident)
    action_mult = _action_risk_multiplier(incident)

    # Final score: apply multiplier to base, then add adjustments
    # This keeps scores in a more reasonable range (0-130ish)
    score_with_multiplier = int(base_score * action_mult)
    score = score_with_multiplier + actor_pts + outcome_adj

    # Clamp to reasonable range (min 0)
    score = max(0, score)

    # Decision thresholds unchanged
    if score < PARKED_MAX:
        decision = "parked"
    elif score <= QUEUED_MAX:
        decision = "queued"
    else:
        decision = "investigating"

    sev_note = ""
    if severity_unrecognized:
        sev_note += f", unrecognized->treated as {DEFAULT_SEVERITY}"

    # Enhanced reason string includes new factors
    reason = (
        f"[severity({severity_pts}{sev_note}) + "
        f"diversity({diversity_pts}) + "
        f"source({source_pts}) + "
        f"anomaly({anomaly_pts})] * "
        f"action_risk({action_mult:.1f}) + "
        f"actor_trust({actor_pts}) + "
        f"outcome_adj({outcome_adj}) = {score} → {decision}"
    )
    return score, reason


def build_explanation(incident: Incident) -> str:
    """Natural-language explanation of the gate decision — which rules fired
    and why, in plain English. Pure string templating over the same factor
    logic that produced the score, so it is guaranteed faithful to the decision
    (an LLM paraphrase could embellish; this cannot) and costs nothing, keeping
    the zero-LLM-spend-on-gated-incidents property intact.
    """
    severity_pts, severity_unrecognized = _severity_points(incident)
    diversity_pts = _diversity_points(incident)
    source_pts = _source_reliability_points(incident)
    anomaly_pts = _anomaly_points(incident)
    base_score = severity_pts + diversity_pts + source_pts + anomaly_pts
    n_types = _distinct_signal_types(incident)
    sources = _sources(incident)
    has_known_source = any(s in SOURCE_RELIABILITY_POINTS for s in sources)

    # NEW: Actor/action/outcome factors (matching score_incident formula)
    actor_pts = _actor_trust_points(incident)
    outcome_adj = _outcome_adjustment(incident)
    action_mult = _action_risk_multiplier(incident)
    score = int(round(base_score * action_mult)) + actor_pts + outcome_adj

    # Derive the gate decision from the score, not incident.status — by the
    # time this renders, the lifecycle may have moved on (analyzing/analyzed).
    if score < PARKED_MAX:
        decision = "parked"
    elif score <= QUEUED_MAX:
        decision = "queued"
    else:
        decision = "investigating"

    parts: list[str] = []

    # 1. The decision itself.
    if decision == "parked":
        parts.append(
            f"This incident was parked as likely noise (score {score}, "
            f"below the {PARKED_MAX}-point review threshold)."
        )
    elif decision == "queued":
        parts.append(
            f"This incident was queued for human review (score {score}) — "
            f"credible enough to flag, but not enough corroboration to justify "
            f"an automatic investigation (threshold {QUEUED_MAX})."
        )
    else:
        parts.append(
            f"This incident scored {score}, above the {QUEUED_MAX}-point "
            f"threshold, and was handed to the automated investigation pipeline."
        )

    # 2. Severity.
    if severity_unrecognized:
        parts.append(
            f"Its reported severity '{incident.severity}' is not a recognized level, "
            f"so it was scored as '{DEFAULT_SEVERITY}' ({severity_pts} pts) rather "
            f"than being ignored."
        )
    else:
        parts.append(f"Severity '{incident.severity}' contributed {severity_pts} pts.")

    # 3. Corroboration across distinct signal types.
    if n_types == 1:
        parts.append(
            f"Only one signal type has been observed on this resource "
            f"({diversity_pts} pts) — no independent corroboration yet."
        )
    else:
        parts.append(
            f"{n_types} distinct signal types on the same resource corroborate "
            f"each other ({diversity_pts} pts)."
        )

    # 4. Source reliability.
    if has_known_source:
        parts.append(
            f"The most reliable reporting source contributed {source_pts} pts."
        )
    else:
        parts.append(
            f"The reporting source '{incident.source}' is not in the high-reliability "
            f"source list, so it received the default score ({source_pts} pts)."
        )

    # 5. Anomaly rules — which fired, or why none did.
    notes = _anomaly_notes(incident)
    if notes:
        parts.append("Anomaly rules fired: " + "; ".join(notes) + ".")
    elif _count_without_baseline(incident):
        parts.append(
            "A call count was reported but with no baseline to compare against, "
            "so the volume rule did not score it as anomalous (0 pts)."
        )
    else:
        parts.append("Nothing in the signal details matched an anomaly rule (0 pts).")

    # 5a. Action risk multiplier (if not 1.0)
    if action_mult != 1.0:
        parts.append(
            f"Action risk multiplier: {action_mult:.1f}× "
            f"(base score {base_score} → {int(round(base_score * action_mult))})."
        )

    # 5b. Actor trust adjustment (if non-zero)
    if actor_pts != 0:
        parts.append(f"Actor trust contributed {actor_pts:+d} pts.")

    # 5c. Outcome adjustment (if non-zero)
    if outcome_adj != 0:
        parts.append(f"Outcome adjustment contributed {outcome_adj:+d} pts.")

    # 6. What happens next.
    if decision == "parked":
        parts.append(
            "No investigation was run and no LLM cost was incurred. It will be "
            "re-scored automatically if a related signal arrives on the same "
            "resource within the 10-minute correlation window."
        )
    elif decision == "queued":
        parts.append(
            "No LLM cost has been incurred. It will escalate automatically if a "
            "corroborating signal correlates in on the same resource within the "
            "10-minute correlation window."
        )

    return " ".join(parts)


def apply(incident: Incident) -> None:
    """Score the incident and write status + fp_score + fp_decision_reason in place."""
    score, reason = score_incident(incident)
    incident.fp_score = score
    incident.fp_decision_reason = reason
    if score < PARKED_MAX:
        incident.status = "parked"
    elif score <= QUEUED_MAX:
        incident.status = "queued"
    else:
        incident.status = "investigating"
