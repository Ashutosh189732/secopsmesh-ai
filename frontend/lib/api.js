const API_BASE = process.env.NEXT_PUBLIC_API_BASE || "http://127.0.0.1:8000";

// Sent only if the backend's API_KEY gate is enabled. Unset for the demo, so
// no header is added. Note: a browser-only client necessarily exposes this to
// the page — it matches the backend's POC-grade shared-secret gate, not a
// substitute for real auth. (The report link below is a plain <a href> and
// can't carry a header; enabling API_KEY would need a different report flow.)
const API_KEY = process.env.NEXT_PUBLIC_API_KEY;

function authHeaders() {
  return API_KEY ? { "X-API-Key": API_KEY } : {};
}

export async function fetchIncidents() {
  const res = await fetch(`${API_BASE}/api/incidents`, {
    cache: "no-store",
    headers: authHeaders(),
  });
  if (!res.ok) throw new Error(`GET /api/incidents failed: ${res.status}`);
  return res.json();
}

export async function fetchStats() {
  const res = await fetch(`${API_BASE}/api/stats`, {
    cache: "no-store",
    headers: authHeaders(),
  });
  if (!res.ok) throw new Error(`GET /api/stats failed: ${res.status}`);
  return res.json();
}

export async function fetchIncident(id) {
  const res = await fetch(`${API_BASE}/api/incidents/${id}`, {
    cache: "no-store",
    headers: authHeaders(),
  });
  if (!res.ok) throw new Error(`GET /api/incidents/${id} failed: ${res.status}`);
  return res.json();
}

export function reportUrl(id) {
  return `${API_BASE}/api/incidents/${id}/report`;
}

// On-demand LLM paraphrase of the FP-gate decision. The only route by which a
// gated incident ever costs inference — triggered by an explicit user click,
// cached server-side so repeat clicks are free.
export async function explainIncident(id) {
  const res = await fetch(`${API_BASE}/api/incidents/${id}/explain`, {
    method: "POST",
    headers: authHeaders(),
  });
  if (!res.ok) {
    let detail = `POST /api/incidents/${id}/explain failed: ${res.status}`;
    try {
      const body = await res.json();
      if (body.detail) detail = body.detail;
    } catch {
      /* keep default */
    }
    throw new Error(detail);
  }
  return res.json();
}

// Manually trigger investigation for a parked/queued incident, overriding the
// FP gate decision. Allows operators to escalate incidents the deterministic
// gate scored below the investigating threshold.
export async function triggerInvestigation(id) {
  const res = await fetch(`${API_BASE}/api/incidents/${id}/investigate`, {
    method: "POST",
    headers: authHeaders(),
  });
  if (!res.ok) {
    let detail = `POST /api/incidents/${id}/investigate failed: ${res.status}`;
    try {
      const body = await res.json();
      if (body.detail) detail = body.detail;
    } catch {
      /* keep default */
    }
    throw new Error(detail);
  }
  return res.json();
}
