"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { fetchIncidents, fetchStats } from "../lib/api";
import { severityClasses, statusClasses } from "../lib/badges";

const POLL_MS = 5000;

export default function IncidentListPage() {
  const [incidents, setIncidents] = useState([]);
  const [stats, setStats] = useState(null);
  const [error, setError] = useState(null);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      try {
        const [data, statsData] = await Promise.all([
          fetchIncidents(),
          fetchStats(),
        ]);
        if (!cancelled) {
          setIncidents(data);
          setStats(statsData);
          setError(null);
        }
      } catch (err) {
        if (!cancelled) setError(err.message);
      } finally {
        if (!cancelled) setLoaded(true);
      }
    }

    load();
    const interval = setInterval(load, POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, []);

  return (
    <div>
      <div className="mb-6 flex items-center justify-between">
        <h2 className="text-xl font-semibold text-gray-900">Incidents</h2>
        <span className="text-xs text-gray-400">auto-refreshing every 5s</span>
      </div>

      {error && (
        <div className="mb-4 rounded border border-red-300 bg-red-50 px-4 py-2 text-sm text-red-700">
          Could not reach the API: {error}
        </div>
      )}

      {stats && stats.total_alerts > 0 && (
        <div className="mb-6 grid grid-cols-2 gap-3 sm:grid-cols-4">
          <StatTile label="Total alerts" value={stats.total_alerts} />
          <StatTile
            label="Gated before any LLM"
            value={stats.alerts_gated_pre_llm}
            accent="emerald"
            hint="parked or queued by the deterministic FP gate — zero inference spent"
          />
          <StatTile
            label="Investigated by LLM"
            value={stats.alerts_llm_investigated}
            accent="blue"
          />
          <StatTile
            label="Est. LLM spend avoided"
            value={`$${stats.est_cost_saved_usd.toFixed(2)}`}
            accent="emerald"
            hint={`≈ ${stats.llm_calls_avoided} LLM calls avoided (${stats.assumptions.avg_llm_calls_per_investigation}/investigation × $${stats.assumptions.est_cost_per_llm_call_usd}) — estimate`}
          />
        </div>
      )}

      {loaded && incidents.length === 0 && !error && (
        <div className="rounded border border-dashed border-gray-300 bg-white px-6 py-12 text-center text-gray-500">
          No incidents yet. POST a signal to <code>/api/signals</code> to see one appear here.
        </div>
      )}

      {incidents.length > 0 && (
        <div className="overflow-hidden rounded border border-gray-200 bg-white">
          <table className="w-full text-left text-sm">
            <thead className="bg-gray-50 text-xs uppercase text-gray-500">
              <tr>
                <th className="px-4 py-3">Resource</th>
                <th className="px-4 py-3">Severity</th>
                <th className="px-4 py-3">FP Score</th>
                <th className="px-4 py-3">Status</th>
                <th className="px-4 py-3">Created</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {incidents.map((incident) => (
                <tr key={incident.id} className="hover:bg-gray-50">
                  <td className="px-4 py-3">
                    <Link
                      href={`/incidents/${incident.id}`}
                      className="font-medium text-blue-700 hover:underline"
                    >
                      {incident.resource_name}
                    </Link>
                    <div className="text-xs text-gray-400">#{incident.id} — {incident.signal_type}</div>
                  </td>
                  <td className="px-4 py-3">
                    <span
                      className={`inline-block rounded-full border px-2 py-0.5 text-xs font-medium ${severityClasses(
                        incident.severity
                      )}`}
                    >
                      {incident.severity}
                    </span>
                  </td>
                  <td
                    className="cursor-help px-4 py-3 font-mono"
                    title={incident.fp_explanation ?? undefined}
                  >
                    {incident.fp_score ?? "—"}
                  </td>
                  <td className="px-4 py-3">
                    <span
                      className={`inline-block rounded-full border px-2 py-0.5 text-xs font-medium ${statusClasses(
                        incident.status
                      )}`}
                    >
                      {incident.status}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-xs text-gray-500">
                    {new Date(incident.created_at + "Z").toLocaleString()}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

const ACCENTS = {
  emerald: "text-emerald-700",
  blue: "text-blue-700",
  gray: "text-gray-900",
};

function StatTile({ label, value, accent = "gray", hint }) {
  return (
    <div className="rounded border border-gray-200 bg-white px-4 py-3" title={hint}>
      <div className="text-xs uppercase tracking-wide text-gray-500">{label}</div>
      <div className={`mt-1 text-2xl font-semibold ${ACCENTS[accent] ?? ACCENTS.gray}`}>
        {value}
      </div>
      {hint && <div className="mt-1 text-[11px] leading-tight text-gray-400">{hint}</div>}
    </div>
  );
}
