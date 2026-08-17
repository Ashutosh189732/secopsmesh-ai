# Demo Scenarios

Four ready-to-run signal payloads, each engineered to land on a specific,
predictable pipeline outcome — so a presenter can pick the exact stage they
want to showcase instead of hoping the FP-gate math cooperates live.

Every score below is computed from the real formula in
[`app/fp_gate.py`](../app/fp_gate.py):

```
score = severity_points + diversity_points + source_reliability_points + anomaly_points
severity:    critical=40, high=30, medium=15, low=5
             (capped at 20 when NO recognized source backs the incident —
              an unknown source can't self-declare critical)
diversity:   1 distinct signal_type=10, 2=25, 3+=40 (capped)
             (rewards different corroborating signal TYPES, not repetition of one)
source:      azure_monitor=20, kubernetes=18, github_commits=16, iam_logs=14, unknown=8
anomaly:     0-15 from the signal details — call-volume-vs-baseline ratio,
             public-read bucket (+10), LargeDataUpload >= 1GB (+5); max across signals
< 40 -> parked   40-80 -> queued   > 80 -> investigating
```

Run each scenario against a **fresh backend** (or at least a resource name
no earlier scenario has used) — signals sharing a `resource_name` within a
10-minute window correlate into one incident, so reusing a name mid-demo will
merge scenarios together.

---

## Scenario 1 — Parked (noise, gate stops it before any LLM spend)

One low-severity signal from an unrecognized source. This is the "the system
correctly ignores this" moment — worth showing first so the FP gate reads as
a real filter, not a rubber stamp.

```bash
curl -X POST http://127.0.0.1:8000/api/signals \
  -H "Content-Type: application/json" \
  -d '{
    "signal_type": "UnauthorizedAPICall",
    "resource_name": "dev-sandbox-worker-03",
    "severity": "low",
    "source": "endpoint_agent",
    "details": {"caller": "test-runner", "api": "internal.healthcheck", "note": "likely CI noise"}
  }'
```

**Expected:** `5 (low) + 10 (1 type) + 8 (unknown source) + 0 (anomaly) = 23 → parked`.
`GET /api/incidents` shows it with `status: "parked"` and no evidence/policy/
root-cause fields populated — the orchestrator never runs.

---

## Scenario 2 — Queued (real signal, not yet worth a full investigation)

A single higher-severity signal, but only one signal and a mid-trust source —
enough to flag, not enough to spin up the LLM chain yet.

```bash
curl -X POST http://127.0.0.1:8000/api/signals \
  -H "Content-Type: application/json" \
  -d '{
    "signal_type": "UnauthorizedAPICall",
    "resource_name": "billing-service-prod",
    "severity": "high",
    "source": "iam_logs",
    "details": {"caller": "svc-reporting", "api": "azure.keyvault.secrets.get", "call_count_last_hour": 12}
  }'
```

**Expected:** `30 (high) + 10 (1 type) + 14 (iam_logs) + 0 (anomaly) = 54 → queued`.
(The `call_count_last_hour: 12` alone scores no anomaly — the volume rule needs a
`baseline_call_count_last_hour` to compare against.)
Good moment to point out this incident is sitting in the queue, waiting for a
correlated second signal on the same resource to push it over the threshold —
the system doesn't just charge ahead on a single medium-confidence data point.
(Manual analyst escalation is a natural next feature, but is not implemented —
don't promise it live.)

---

## Scenario 3 — Full investigation, GDPR path (flagship demo)

The plan's canonical scenario: a storage bucket goes public, then a large
upload lands in it, then a suspicious API call fires from the same
environment — three signals, same resource, correlate into one incident that
blows straight past the `investigating` threshold. This is the one that
exercises all ten pipeline stages end to end, and is the one most likely to
trip the Root Cause Agent's `gdpr_flag` (personal-data export + public
bucket is exactly Article 32 language).

```bash
curl -X POST http://127.0.0.1:8000/api/signals \
  -H "Content-Type: application/json" \
  -d '{
    "signal_type": "PublicStorageBucket",
    "resource_name": "prod-analytics-exports",
    "severity": "critical",
    "source": "azure_monitor",
    "details": {"bucket_acl": "public-read"}
  }'

curl -X POST http://127.0.0.1:8000/api/signals \
  -H "Content-Type: application/json" \
  -d '{
    "signal_type": "LargeDataUpload",
    "resource_name": "prod-analytics-exports",
    "severity": "high",
    "source": "azure_monitor",
    "details": {"size_gb": 4.2, "file_name": "customer_export.csv"}
  }'

curl -X POST http://127.0.0.1:8000/api/signals \
  -H "Content-Type: application/json" \
  -d '{
    "signal_type": "UnauthorizedAPICall",
    "resource_name": "prod-analytics-exports",
    "severity": "medium",
    "source": "iam_logs",
    "details": {"caller": "svc-deploy-bot", "api": "azure.openai.completions"}
  }'
```

**Expected:** merges into one incident, `correlated_count: 3`,
`severity: "critical"` (escalates to worst signal), score
`40 (critical) + 40 (3 types) + 20 (azure_monitor) + 10 (public-read bucket) = 110
→ investigating`. (Signal 1 alone scores 80 → queued and signal 2 pushes it to 95 →
investigating, so the orchestrator kicks off once the second signal correlates.)
Within ~10-20s the orchestrator
populates `evidence` (2-3 items citing the `azure_monitor` deployment change,
the Terraform commit, and the anomalous IAM call volume); within another
~15-30s `policies`, `root_cause` (watch for `gdpr_flag: true` and
`evidence_ids_cited`), `risk_assessment`, and `remediation_plan` fill in.
This is the scenario to walk through all 6 dashboard tabs on.

---

## Scenario 4 — Full investigation, access-control path (no GDPR angle)

A second flagship-tier scenario on a *different* resource, so it runs
independently of Scenario 3. Two signals reach `investigating` faster here
because the second signal's source (`azure_monitor`, trust 20) out-trusts the
first's (`iam_logs`, trust 14) — the FP gate always uses the single most
reliable source seen on the incident, not an average. Useful for showing that
the Policy Agent surfaces *different* excerpts (SOC2 CC6 / ISO 27001 A.9 —
access control — rather than GDPR) depending on what the evidence actually
describes.

```bash
curl -X POST http://127.0.0.1:8000/api/signals \
  -H "Content-Type: application/json" \
  -d '{
    "signal_type": "UnauthorizedAPICall",
    "resource_name": "internal-ml-gateway",
    "severity": "critical",
    "source": "iam_logs",
    "details": {"caller": "svc-deploy-bot", "api": "azure.openai.completions", "call_count_last_hour": 47, "baseline_call_count_last_hour": 2}
  }'

curl -X POST http://127.0.0.1:8000/api/signals \
  -H "Content-Type: application/json" \
  -d '{
    "signal_type": "LargeDataUpload",
    "resource_name": "internal-ml-gateway",
    "severity": "high",
    "source": "azure_monitor",
    "details": {"size_gb": 1.1, "file_name": "model_eval_batch.csv"}
  }'
```

**Expected:** first signal alone scores `40 (critical) + 10 (1 type) + 14 (iam_logs)
+ 15 (47-vs-2 call-volume anomaly, capped at 15) = 79` (queued); once the second
correlates, `correlated_count: 2`, now 2 distinct types and the best source becomes
`azure_monitor`, so the score jumps to `40 + 25 + 20 + 15 = 100 → investigating`.
Good scenario for showing the FP gate re-scoring an existing incident as new
evidence correlates in, not just at creation time.

> **Narration caveat:** the mocked connectors in
> [`app/orchestrator/connectors.py`](../app/orchestrator/connectors.py) return
> the same fixed evidence text no matter what resource or scenario triggered
> them — `azure_monitor` always describes a storage-bucket ACL change for a
> CDN migration, `github_commits` always cites the same Terraform diff. That
> evidence text was written for Scenario 3's storage narrative, so if you run
> Scenario 4 and click into the Evidence tab, don't narrate it as "the ML
> gateway's access logs" — the FP-gate scoring and correlation behavior are
> real and dynamic, but the evidence *content* is Scenario 3's regardless of
> which scenario asked for it. Lead with Scenario 3 for anything where the
> Evidence tab needs to make narrative sense; use Scenario 4 only to show the
> scoring/re-scoring behavior, not the evidence content.

---

## Suggested walkthrough order

1. **Scenario 1** — "here's noise, the gate stops it, zero LLM cost."
2. **Scenario 2** — "here's a real signal that's not enough on its own yet."
3. **Scenario 3** — full walkthrough of all 6 tabs, PDF report download.
4. **Scenario 4** (time permitting) — same pipeline, different policy angle,
   demonstrates re-scoring on correlation rather than a single-shot decision.

Between POSTing Scenario 3 or 4's signals and checking the dashboard, leave
20-40 seconds for the orchestrator (evidence → policy → root cause → risk →
remediation) to finish — the incident list auto-polls every 5s so the status
badge will visibly move from `investigating` through to fully populated
without a manual refresh.
