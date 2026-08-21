"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { explainIncident, fetchIncident, reportUrl, triggerInvestigation } from "../../../lib/api";
import {
  severityClasses,
  statusClasses,
  priorityClasses,
  actorTypeClasses,
  actionClasses,
  outcomeClasses,
  actorIcon,
  outcomeIcon,
  severityDotClasses
} from "../../../lib/badges";

const POLL_MS = 5000;
const TABS = ["Timeline", "Evidence", "Policies", "Root Cause", "Risk", "Remediation"];

export default function IncidentDetailPage({ params }) {
  const { id } = params;
  const [incident, setIncident] = useState(null);
  const [error, setError] = useState(null);
  const [activeTab, setActiveTab] = useState("Timeline");
  const [approved, setApproved] = useState({});

  useEffect(() => {
    let cancelled = false;

    async function load() {
      try {
        const data = await fetchIncident(id);
        if (!cancelled) {
          setIncident(data);
          setError(null);
        }
      } catch (err) {
        if (!cancelled) setError(err.message);
      }
    }

    load();
    const interval = setInterval(load, POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [id]);

  if (error) {
    return (
      <div className="rounded border border-red-300 bg-red-50 px-4 py-3 text-sm text-red-700">
        Could not load incident #{id}: {error}
      </div>
    );
  }

  if (!incident) {
    return <div className="text-sm text-gray-500">Loading incident #{id}...</div>;
  }

  return (
    <div>
      <Link href="/" className="text-sm text-blue-700 hover:underline">
        &larr; Back to incidents
      </Link>

      <div className="mt-3 flex items-start justify-between">
        <div>
          <h2 className="text-xl font-semibold text-gray-900">
            {incident.resource_name}{" "}
            <span className="text-sm font-normal text-gray-400">#{incident.id}</span>
          </h2>
          <div className="mt-1 flex gap-2">
            <span
              className={`inline-block rounded-full border px-2 py-0.5 text-xs font-medium ${severityClasses(
                incident.severity
              )}`}
            >
              {incident.severity}
            </span>
            <span
              className={`inline-block rounded-full border px-2 py-0.5 text-xs font-medium ${statusClasses(
                incident.status
              )}`}
            >
              {incident.status}
            </span>
          </div>
        </div>
        <a
          href={reportUrl(incident.id)}
          className="rounded bg-gray-900 px-4 py-2 text-sm font-medium text-white hover:bg-gray-700"
        >
          Download Report
        </a>
      </div>

      {/* FP Gate decision, shown prominently per the plan */}
      <FpGateCard incident={incident} />

      {/* Manual investigation trigger for parked/queued incidents */}
      <ManualTriggerCard incident={incident} />

      <div className="mt-6 border-b border-gray-200">
        <nav className="-mb-px flex gap-6">
          {TABS.map((tab) => (
            <button
              key={tab}
              onClick={() => setActiveTab(tab)}
              className={`border-b-2 px-1 py-2 text-sm font-medium ${
                activeTab === tab
                  ? "border-gray-900 text-gray-900"
                  : "border-transparent text-gray-500 hover:text-gray-700"
              }`}
            >
              {tab}
            </button>
          ))}
        </nav>
      </div>

      <div className="mt-6">
        {activeTab === "Timeline" && <TimelineTab incident={incident} />}
        {activeTab === "Evidence" && <EvidenceTab incident={incident} />}
        {activeTab === "Policies" && <PoliciesTab incident={incident} />}
        {activeTab === "Root Cause" && <RootCauseTab incident={incident} />}
        {activeTab === "Risk" && <RiskTab incident={incident} />}
        {activeTab === "Remediation" && (
          <RemediationTab incident={incident} approved={approved} setApproved={setApproved} />
        )}
      </div>
    </div>
  );
}

function ManualTriggerCard({ incident }) {
  const [triggering, setTriggering] = useState(false);
  const [triggerError, setTriggerError] = useState(null);

  // Only show for parked/queued incidents
  const canTrigger = ["parked", "queued"].includes(incident.status);
  if (!canTrigger) return null;

  async function handleTrigger() {
    setTriggering(true);
    setTriggerError(null);
    try {
      await triggerInvestigation(incident.id);
      // Poll will pick up status change automatically
    } catch (err) {
      setTriggerError(err.message);
    } finally {
      setTriggering(false);
    }
  }

  return (
    <div className="mt-4 rounded border border-amber-200 bg-amber-50 px-4 py-3">
      <div className="text-sm font-semibold text-amber-900">
        Manual Investigation Override
      </div>
      <p className="mt-1 text-sm text-amber-800">
        This incident was {incident.status} by the FP gate. You can override
        this decision and trigger a full LLM investigation.
      </p>
      <button
        onClick={handleTrigger}
        disabled={triggering}
        className="mt-3 rounded bg-amber-600 px-4 py-2 text-sm font-medium text-white hover:bg-amber-700 disabled:opacity-50"
      >
        {triggering ? "Triggering investigation..." : "🔍 Investigate Now"}
      </button>
      {triggerError && (
        <div className="mt-2 text-xs text-red-600">
          Could not trigger: {triggerError}
        </div>
      )}
    </div>
  );
}

function FpGateCard({ incident }) {
  const [explaining, setExplaining] = useState(false);
  const [explainError, setExplainError] = useState(null);
  const [llmText, setLlmText] = useState(null);

  // Prefer the freshly returned text; fall back to the persisted cache the
  // incident poll delivers.
  const aiExplanation = llmText ?? incident.llm_explanation;

  async function handleExplain() {
    setExplaining(true);
    setExplainError(null);
    try {
      const result = await explainIncident(incident.id);
      setLlmText(result.explanation);
    } catch (err) {
      setExplainError(err.message);
    } finally {
      setExplaining(false);
    }
  }

  return (
    <div className="mt-4 rounded border border-gray-200 bg-white px-4 py-3">
      <div className="flex items-center justify-between">
        <div className="text-sm font-semibold text-gray-700">False-Positive Gate</div>
        <div className="text-sm text-gray-600">
          Score: <span className="font-mono font-semibold">{incident.fp_score ?? "—"}</span>
        </div>
      </div>

      {/* Deterministic explanation — generated by the gate itself, zero LLM cost */}
      {incident.fp_explanation && (
        <p className="mt-2 text-sm leading-relaxed text-gray-700">{incident.fp_explanation}</p>
      )}

      {/* Exact arithmetic, demoted to fine print for auditability */}
      {incident.fp_decision_reason && (
        <div className="mt-2 font-mono text-[11px] text-gray-400">{incident.fp_decision_reason}</div>
      )}

      <div className="mt-3 border-t border-gray-100 pt-3">
        {aiExplanation ? (
          <div>
            <div className="mb-1 flex items-center gap-2 text-xs font-medium text-violet-700">
              <span>✨ AI explanation</span>
              <span className="font-normal text-gray-400">generated on demand by the LLM</span>
            </div>
            <p className="text-sm leading-relaxed text-gray-700">{aiExplanation}</p>
          </div>
        ) : (
          <button
            onClick={handleExplain}
            disabled={explaining}
            className="rounded border border-violet-300 bg-violet-50 px-3 py-1.5 text-xs font-medium text-violet-700 hover:bg-violet-100 disabled:opacity-50"
          >
            {explaining ? "Asking the model…" : "✨ Explain with AI"}
          </button>
        )}
        {explainError && (
          <div className="mt-2 text-xs text-red-600">Could not generate explanation: {explainError}</div>
        )}
      </div>
    </div>
  );
}

function EmptyState({ text }) {
  return (
    <div className="rounded border border-dashed border-gray-300 bg-white px-6 py-10 text-center text-sm text-gray-500">
      {text}
    </div>
  );
}

function TimelineTab({ incident }) {
  if (!incident.timeline?.length) return <EmptyState text="No timeline events yet." />;

  // Helper: Calculate time gap between events in seconds
  function calculateTimeGap(prevTimestamp, currentTimestamp) {
    const prev = new Date(prevTimestamp);
    const curr = new Date(currentTimestamp);
    return Math.floor((curr - prev) / 1000);
  }

  // Helper: Format duration as human-readable string
  function formatDuration(seconds) {
    if (seconds < 60) return `${seconds}s`;
    const minutes = Math.floor(seconds / 60);
    if (minutes < 60) return `${minutes}m ${seconds % 60}s`;
    const hours = Math.floor(minutes / 60);
    return `${hours}h ${minutes % 60}m`;
  }

  // Helper: Detect anomalies from event details
  function detectAnomalies(details) {
    if (!details || typeof details !== "object") return [];
    const anomalies = [];

    if (details.bucket_acl === "public-read") {
      anomalies.push({ key: "public-bucket", description: "Public storage" });
    }

    if (details.size_gb && details.size_gb >= 1.0) {
      anomalies.push({ key: "large-upload", description: `${details.size_gb} GB upload` });
    }

    // Call volume anomaly - matches backend fp_gate.py lines 186-195
    const callCount = details.call_count_last_hour;
    const baseline = details.baseline_call_count_last_hour;
    if (callCount != null && baseline != null && callCount > baseline * 3) {
      const ratio = Math.round(callCount / baseline);
      anomalies.push({ key: "call-volume", description: `${ratio}× baseline calls` });
    }

    return anomalies;
  }

  // Helper: Calculate approximate FP contribution up to this signal
  // Note: This is a simplified display calculation. Actual scoring in fp_gate.py
  function calculateFPContribution(event, index, timeline, incidentSeverity) {
    const SEVERITY_PTS = { critical: 40, high: 30, medium: 15, low: 5 };
    const SOURCE_PTS = {
      azure_monitor: 20, kubernetes: 18, github_commits: 16, iam_logs: 14,
      waf_alert: 8, endpoint_agent: 8, vuln_scanner: 5
    };
    const ACTOR_TRUST = { system: 10, service: 8, user: 5, anonymous: 2, other: 3 };
    const ACTION_RISK = { delete: 1.2, execute: 1.2, create: 1.1, update: 1.0, read: 0.9, access: 1.0, other: 1.0 };
    const OUTCOME_ADJ = { success: 0, partial: 5, failure: -5, blocked: -10 };

    // Backend takes worst severity across all signals (stored in incident.severity)
    // which may escalate as signals arrive
    const signalsUpToNow = timeline.slice(0, index + 1);

    // Severity: Use incident severity (escalates to worst across all signals)
    const severityPts = SEVERITY_PTS[incidentSeverity?.toLowerCase()] || 15;

    // Diversity: Count distinct signal types up to now (10 + 15 per additional type)
    const uniqueTypes = new Set(signalsUpToNow.map(e => e.signal)).size;
    const diversityPts = uniqueTypes === 1 ? 10 : 10 + (uniqueTypes - 1) * 15;

    // Source: Best (highest trust) source up to now
    const sourcePts = Math.max(...signalsUpToNow.map(e => SOURCE_PTS[e.source] || 8));

    // Anomaly: Max anomaly points across all signals up to now
    const anomalyPts = Math.max(...signalsUpToNow.map(e => {
      let pts = 0;

      // Public bucket = 10 pts
      if (e.details?.bucket_acl === "public-read") {
        pts = Math.max(pts, 10);
      }

      // Large upload (>=1GB) = 5 pts
      if (e.details?.size_gb >= 1.0) {
        pts = Math.max(pts, 5);
      }

      // Call volume anomaly - matches fp_gate.py lines 186-195
      const callCount = e.details?.call_count_last_hour;
      const baseline = e.details?.baseline_call_count_last_hour;
      if (callCount != null && baseline != null && callCount > 0) {
        const ratio = callCount / Math.max(baseline, 1.0);
        const volumePts = Math.min(15, Math.floor(ratio));  // ratio->int, cap at 15
        pts = Math.max(pts, volumePts);
      }

      return Math.min(15, pts); // Overall anomaly cap at 15
    }), 0);

    // Base score (before multipliers/adjustments)
    const baseScore = severityPts + diversityPts + sourcePts + anomalyPts;

    // Action risk: Highest risk multiplier up to now
    const actionMult = Math.max(...signalsUpToNow.map(e => ACTION_RISK[e.action] || 1.0));

    // Actor trust: Best (highest trust) actor up to now
    const actorPts = Math.max(...signalsUpToNow.map(e =>
      e.actor ? (ACTOR_TRUST[e.actor.type] || 0) : 0
    ), 0);

    // Outcome adjustment: Worst (most suspicious = closest to 0 or positive)
    const outcomeAdj = signalsUpToNow.reduce((worst, e) => {
      const adj = OUTCOME_ADJ[e.outcome] || 0;
      return Math.abs(adj) > Math.abs(worst) ? adj : worst;
    }, 0);

    // Final score formula (matches fp_gate.py):
    // (base * action_mult) + actor + outcome
    const cumulativeScore = Math.max(0, Math.floor(baseScore * actionMult) + actorPts + outcomeAdj);

    // Calculate previous score for delta
    let prevScore = 0;
    if (index > 0) {
      const prevSignals = timeline.slice(0, index);
      const prevUnique = new Set(prevSignals.map(e => e.signal)).size;
      const prevDiversity = prevUnique === 1 ? 10 : 10 + (prevUnique - 1) * 15;
      const prevSource = Math.max(...prevSignals.map(e => SOURCE_PTS[e.source] || 8));
      const prevAnomaly = Math.max(...prevSignals.map(e => {
        let pts = 0;
        if (e.details?.bucket_acl === "public-read") pts = Math.max(pts, 10);
        if (e.details?.size_gb >= 1.0) pts = Math.max(pts, 5);
        return Math.min(15, pts);
      }), 0);
      const prevBase = severityPts + prevDiversity + prevSource + prevAnomaly;
      const prevAction = Math.max(...prevSignals.map(e => ACTION_RISK[e.action] || 1.0));
      const prevActor = Math.max(...prevSignals.map(e =>
        e.actor ? (ACTOR_TRUST[e.actor.type] || 0) : 0
      ), 0);
      const prevOutcome = prevSignals.reduce((worst, e) => {
        const adj = OUTCOME_ADJ[e.outcome] || 0;
        return Math.abs(adj) > Math.abs(worst) ? adj : worst;
      }, 0);
      prevScore = Math.max(0, Math.floor(prevBase * prevAction) + prevActor + prevOutcome);
    }

    const delta = cumulativeScore - prevScore;

    // Threshold detection
    let crossedThreshold = false;
    let newStatus = null;
    if (prevScore <= 80 && cumulativeScore > 80) {
      crossedThreshold = true;
      newStatus = "investigating";
    } else if (prevScore < 40 && cumulativeScore >= 40) {
      crossedThreshold = true;
      newStatus = "queued";
    }

    return { delta, cumulativeScore, crossedThreshold, newStatus };
  }

  return (
    <div className="relative pl-12">
      {/* Vertical connecting line */}
      <div className="absolute left-4 top-0 bottom-0 w-0.5 bg-gray-200" />

      {incident.timeline.map((event, i) => {
        const gap = i > 0 ? calculateTimeGap(incident.timeline[i-1].timestamp, event.timestamp) : null;
        const fpContribution = calculateFPContribution(event, i, incident.timeline, incident.severity);
        const anomalies = detectAnomalies(event.details);

        return (
          <div key={i}>
            {/* Time gap indicator (if gap > 60 seconds) */}
            {gap && gap > 60 && (
              <div className="relative mb-3">
                <div className="ml-8 py-2 text-xs text-gray-400 flex items-center gap-2">
                  <span>⏸</span>
                  <span>{formatDuration(gap)} gap</span>
                </div>
              </div>
            )}

            {/* Timeline event */}
            <div className="relative mb-6">
              {/* Timeline dot - sized by incident severity (escalates as signals arrive) */}
              <div className={`absolute left-[-2rem] top-3 z-10 rounded-full border-4 border-white shadow ${severityDotClasses(incident.severity || "medium")}`} />

              {/* Event card */}
              <div className="rounded border border-gray-200 bg-white px-4 py-3 shadow-sm">
                {/* AI Summary (existing) */}
                {event.summary && (
                  <div className="mb-3 rounded-md bg-violet-50 px-3 py-2 text-sm leading-relaxed text-gray-800">
                    <span className="mr-1 text-violet-600">✨</span>
                    {event.summary}
                  </div>
                )}

                {/* NEW: Badges row - correlation + anomalies */}
                <div className="mb-2 flex flex-wrap gap-2">
                  {i > 0 && (
                    <span
                      className="inline-flex items-center gap-1 rounded-full bg-blue-100 px-2 py-0.5 text-xs text-blue-700 border border-blue-200"
                      title="Same resource within 10-minute correlation window"
                    >
                      🔗 Correlated
                    </span>
                  )}
                  {anomalies.map(anomaly => (
                    <span
                      key={anomaly.key}
                      className="inline-flex items-center gap-1 rounded-full bg-amber-100 px-2 py-0.5 text-xs text-amber-800 border border-amber-200"
                    >
                      ⚠️ {anomaly.description}
                    </span>
                  ))}
                </div>

                {/* Actor row (existing) */}
                {event.actor && (
                  <div className="mb-2 flex items-center gap-2">
                    <span className="text-lg">{actorIcon(event.actor.type)}</span>
                    <span className="text-sm font-semibold text-gray-900">
                      {event.actor.id || "Unknown"}
                    </span>
                    {event.actor.ip_address && (
                      <span className="text-xs text-gray-400">
                        ({event.actor.ip_address})
                      </span>
                    )}
                    <span className={`ml-auto rounded-full border px-2 py-0.5 text-xs font-medium ${actorTypeClasses(event.actor.type)}`}>
                      {event.actor.type}
                    </span>
                  </div>
                )}

                {/* Action + Signal + Outcome (existing) */}
                <div className="flex items-center gap-2">
                  {event.action && (
                    <span className={`rounded border px-2 py-0.5 text-xs font-medium uppercase ${actionClasses(event.action)}`}>
                      {event.action}
                    </span>
                  )}
                  <span className="text-sm font-medium text-gray-800">{event.signal}</span>
                  {event.outcome && (
                    <span className={`ml-auto rounded border px-2 py-0.5 text-xs font-semibold ${outcomeClasses(event.outcome)}`}>
                      {outcomeIcon(event.outcome)} {event.outcome.toUpperCase()}
                    </span>
                  )}
                </div>

                {/* NEW: FP Score contribution */}
                <div className="mt-2 text-xs">
                  <span className="text-gray-500">FP Impact: </span>
                  <span className={fpContribution.crossedThreshold ? "font-bold text-green-600" : "text-gray-700"}>
                    {fpContribution.delta > 0 ? `+${fpContribution.delta}` : fpContribution.delta} pts → Score: {fpContribution.cumulativeScore}
                  </span>
                  {fpContribution.crossedThreshold && (
                    <span className="ml-2 font-semibold text-green-700">
                      ⬆️ Escalated to {fpContribution.newStatus}
                    </span>
                  )}
                </div>

                {/* Timestamps (existing) */}
                <div className="mt-2 flex flex-wrap gap-3 text-xs text-gray-400">
                  {event.event_time && (
                    <span title="When the event actually occurred">
                      ⏱ Event: {new Date(event.event_time).toLocaleString()}
                    </span>
                  )}
                  <span title="When we received the signal">
                    📥 Received: {new Date(event.timestamp).toLocaleString()}
                  </span>
                  <span className="text-gray-500">Source: {event.source}</span>
                </div>

                {/* Technical details (existing) */}
                {event.details && Object.keys(event.details).filter(k => k !== "summary").length > 0 && (
                  <details className="mt-2">
                    <summary className="cursor-pointer text-xs text-gray-500 hover:text-gray-700">
                      Technical details
                    </summary>
                    <div className="mt-1 text-xs text-gray-500">
                      {Object.entries(event.details)
                        .filter(([k]) => k !== "summary")
                        .map(([k, v]) => (
                          <span key={k} className="mr-3 whitespace-nowrap">
                            <strong>{k}:</strong> {JSON.stringify(v)}
                          </span>
                        ))}
                    </div>
                  </details>
                )}
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}

function ConfidenceBar({ value }) {
  const pct = Math.round((value || 0) * 100);
  const color = pct >= 85 ? "bg-green-500" : pct >= 60 ? "bg-yellow-500" : "bg-red-500";
  return (
    <div className="flex items-center gap-2">
      <div className="h-2 w-24 overflow-hidden rounded-full bg-gray-200">
        <div className={`h-full ${color}`} style={{ width: `${pct}%` }} />
      </div>
      <span className="font-mono text-xs text-gray-600">{value?.toFixed?.(2) ?? value}</span>
    </div>
  );
}

function EvidenceTab({ incident }) {
  if (!incident.evidence?.length) return <EmptyState text="No evidence collected yet." />;
  return (
    <div className="overflow-hidden rounded border border-gray-200 bg-white">
      <table className="w-full text-left text-sm">
        <thead className="bg-gray-50 text-xs uppercase text-gray-500">
          <tr>
            <th className="px-4 py-2">ID</th>
            <th className="px-4 py-2">Connector</th>
            <th className="px-4 py-2">Confidence</th>
            <th className="px-4 py-2">Data preview</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-100">
          {incident.evidence.map((item) => (
            <tr key={item.id}>
              <td className="px-4 py-3 font-mono text-xs text-gray-500">{item.id}</td>
              <td className="px-4 py-3 font-medium text-gray-800">{item.connector}</td>
              <td className="px-4 py-3">
                <ConfidenceBar value={item.confidence} />
              </td>
              <td className="px-4 py-3 font-mono text-xs text-gray-500">
                {Object.entries(item.data || {})
                  .slice(0, 3)
                  .map(([k, v]) => `${k}=${v}`)
                  .join(", ")}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {incident.evidence_guard_triggered && (
        <div className="border-t border-amber-200 bg-amber-50 px-4 py-2 text-xs text-amber-800">
          The 90-second investigation guard was triggered — evidence collection was cut short.
        </div>
      )}
    </div>
  );
}

function PoliciesTab({ incident }) {
  if (!incident.policies?.length) return <EmptyState text="No policy matches retrieved yet." />;
  return (
    <div className="grid gap-4 sm:grid-cols-2">
      {incident.policies.map((policy) => (
        <div key={policy.policy_id} className="rounded border border-gray-200 bg-white p-4">
          <div className="flex items-center justify-between">
            <div className="font-medium text-gray-900">{policy.title}</div>
            <span className="rounded-full bg-gray-100 px-2 py-0.5 text-xs font-mono text-gray-600">
              {policy.relevance_score?.toFixed?.(2)}
            </span>
          </div>
          <p className="mt-2 whitespace-pre-line text-xs text-gray-500">{policy.excerpt}</p>
        </div>
      ))}
    </div>
  );
}

function RootCauseTab({ incident }) {
  const rc = incident.root_cause;
  if (!rc) return <EmptyState text="Root cause analysis not yet available." />;
  const cited = new Set(rc.evidence_ids_cited || []);
  return (
    <div className="space-y-4">
      <div className="rounded border border-gray-200 bg-white p-4">
        <p className="text-sm text-gray-800">{rc.root_cause}</p>
        <div className="mt-3 flex flex-wrap items-center gap-2 text-xs">
          <span className="rounded-full bg-gray-100 px-2 py-0.5 font-mono text-gray-600">
            confidence {rc.confidence?.toFixed?.(2)}
          </span>
          {rc.gdpr_flag && (
            <span className="rounded-full bg-red-100 px-2 py-0.5 font-medium text-red-800">
              GDPR flagged
            </span>
          )}
          {(incident.evidence || []).map((item) => (
            <span
              key={item.id}
              className={`rounded-full border px-2 py-0.5 font-mono ${
                cited.has(item.id)
                  ? "border-blue-400 bg-blue-100 text-blue-800"
                  : "border-gray-200 bg-gray-50 text-gray-400"
              }`}
              title={cited.has(item.id) ? "cited" : "not cited"}
            >
              {item.id}
            </span>
          ))}
        </div>
      </div>

      {rc.alternative_hypotheses?.length > 0 && (
        <div className="rounded border border-gray-200 bg-white p-4">
          <div className="mb-2 text-sm font-semibold text-gray-700">Alternative hypotheses</div>
          <ul className="list-disc space-y-2 pl-5 text-sm text-gray-600">
            {rc.alternative_hypotheses.map((alt, i) => (
              <li key={i}>{alt}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function RiskTab({ incident }) {
  const ra = incident.risk_assessment;
  if (!ra) return <EmptyState text="Risk assessment not yet available." />;
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <span
          className={`inline-block rounded-full border px-3 py-1 text-sm font-semibold ${severityClasses(
            ra.severity
          )}`}
        >
          {ra.severity} — {ra.score}/100
        </span>
        {ra.gdpr_flag && (
          <span className="rounded-full bg-red-100 px-3 py-1 text-sm font-medium text-red-800">
            GDPR flagged
          </span>
        )}
        <span className="text-xs text-gray-500">{ra.affected_estimate}</span>
      </div>
      <div className="rounded border border-gray-200 bg-white p-4">
        <div className="text-sm font-semibold text-gray-700">Business impact</div>
        <p className="mt-1 text-sm text-gray-600">{ra.business_impact}</p>
      </div>
      <div className="rounded border border-gray-200 bg-white p-4">
        <div className="text-sm font-semibold text-gray-700">Compliance impact</div>
        <p className="mt-1 text-sm text-gray-600">{ra.compliance_impact}</p>
      </div>
    </div>
  );
}

function RemediationTab({ incident, approved, setApproved }) {
  const plan = incident.remediation_plan;
  if (!plan?.steps?.length) return <EmptyState text="No remediation plan generated yet." />;
  return (
    <div>
      <div className="mb-4 rounded border border-blue-200 bg-blue-50 px-4 py-2 text-xs text-blue-800">
        No action here executes anything. "Mark Approved" only updates this screen — it is not
        wired to any backend action.
      </div>
      <div className="space-y-3">
        {plan.steps.map((step) => {
          const isApproved = approved[step.step_number];
          return (
            <div key={step.step_number} className="rounded border border-gray-200 bg-white p-4">
              <div className="flex items-start justify-between gap-4">
                <div>
                  <div className="text-sm font-medium text-gray-900">
                    Step {step.step_number}: {step.action}
                  </div>
                  <div className="mt-2 flex flex-wrap gap-2 text-xs">
                    <span className="rounded-full bg-gray-100 px-2 py-0.5 text-gray-600">
                      owner: {step.owner}
                    </span>
                    <span
                      className={`rounded-full border px-2 py-0.5 ${priorityClasses(step.priority)}`}
                    >
                      {step.priority} priority
                    </span>
                    <span className="rounded-full bg-gray-100 px-2 py-0.5 text-gray-600">
                      {step.estimated_time}
                    </span>
                    {step.requires_human_approval && (
                      <span className="rounded-full bg-amber-100 px-2 py-0.5 text-amber-800">
                        requires human approval
                      </span>
                    )}
                  </div>
                </div>
                <button
                  onClick={() =>
                    setApproved((prev) => ({ ...prev, [step.step_number]: !prev[step.step_number] }))
                  }
                  className={`shrink-0 rounded px-3 py-1.5 text-xs font-medium ${
                    isApproved
                      ? "bg-green-600 text-white"
                      : "border border-gray-300 bg-white text-gray-700 hover:bg-gray-50"
                  }`}
                >
                  {isApproved ? "Approved ✓" : "Mark Approved"}
                </button>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
