# SecOpsMeshAI — Hackathon POC Plan
**7-day war room · Ship a working agentic demo, not a full product**

---

## The Golden Rule

> Scope ruthlessly. You're not building SecOpsMeshAI. You're building a demo that *proves* SecOpsMeshAI can work. Mock everything you can. Make one incident scenario work perfectly end-to-end.

---

## The One Demo Scenario

> A storage bucket goes public → a large CSV is uploaded → Azure OpenAI is called → deployment history shows a misconfigured release 6 minutes earlier.

Every agent, every mock, every UI screen should be built around making **this scenario** shine.

---

## Scoped POC — What You're Actually Building

From 9 components down to **4 real things + 2 mocks + 1 UI**:

| Component | POC Approach |
|---|---|
| Signal Intake | ✅ Real — FastAPI endpoint |
| Correlation Engine | ✅ Real — pure Python, no LLM |
| FP Gate | ✅ Real — rule-based scoring |
| LangGraph Orchestrator | ✅ Real — the centerpiece |
| Evidence Agent | 🟡 Mocked — 4 hardcoded connectors |
| Policy Agent | 🟡 Real-ish — ChromaDB + 5 markdown files |
| Root Cause Agent | ✅ Real — Claude Sonnet 5 (`anthropic/claude-sonnet-5`) via OpenRouter, with structured output |
| Risk + Remediation | ✅ Real — LLM + deterministic scoring |
| Report Generator | ✅ Real — PDF download |
| Response Executor | ❌ Cut — mention only in roadmap slide |

---

## Day 1 — Scaffolding + Signal Intake

**Estimated effort:** ~8h  
**Goal:** By end of day, `POST /api/signals` accepts a raw alert JSON and you can see the incident in a database.

### Technology

| Tool | Purpose |
|---|---|
| **FastAPI** | REST API framework — async, Pydantic-native, minimal boilerplate |
| **PostgreSQL** | Primary database for incidents table |
| **Docker + docker-compose** | Local environment: app + postgres + redis in one command |
| **Pydantic** | Schema validation for incoming signal payloads |
| **Redis** | Event queue for signals (simple list push/pop for now) |

### Tasks

- [ ] Create GitHub repo, README skeleton, MIT license
- [ ] Bootstrap FastAPI app with `/health` endpoint
- [ ] Set up PostgreSQL via Docker — one `incidents` table
- [ ] Write `docker-compose.yml` covering app + postgres + redis
- [ ] Add `.env` with `OPENROUTER_API_KEY` placeholder and `.env.example` (LLM calls route through OpenRouter, not Anthropic directly)
- [ ] Implement `POST /api/signals` — Pydantic validation, 3 signal types hardcoded: `PublicStorageBucket`, `LargeDataUpload`, `UnauthorizedAPICall`
- [ ] Write signals to DB with `status='new'`, severity, timestamp, source
- [ ] `GET /api/incidents` — list all incidents (the UI will consume this)
- [ ] Write 3 curl test commands in the README

### End-of-Day Check
`docker-compose up` from scratch → curl the signal endpoint → row appears in DB. ✓

---

## Day 2 — Correlation Engine + False-Positive Gate

**Estimated effort:** ~6h  
**Goal:** Multiple related alerts collapse into one incident. Low-confidence noise gets parked before any LLM runs.

### Technology

| Tool | Purpose |
|---|---|
| **Pure Python** | Correlation logic and FP scoring — no LLM, no external dependencies |
| **PostgreSQL** | Persist incident timelines and gate decisions |
| **SQLAlchemy** | ORM for incident reads/writes |

> **Why no LLM here?** Alert correlation is a solved deterministic problem. Using an LLM here wastes money and adds hallucination risk for zero benefit.

### Tasks

**Correlation Engine**
- [ ] Group signals by `resource_name` + 10-minute time window
- [ ] If 2+ signals share a resource in that window → merge into one incident
- [ ] Build `incident.timeline`: `[{signal, timestamp, source}]` ordered chronologically
- [ ] Store `correlated_count` on each incident

**False-Positive Gate** *(addresses Gap 1)*
- [ ] Score each incident 0–100: severity (40 pts) + correlated_count (40 pts) + source_reliability (20 pts)
- [ ] `score < 40` → `status='parked'`, log reason, stop pipeline
- [ ] `score 40–65` → `status='queued'`, flag for human triage
- [ ] `score > 65` → `status='investigating'`, proceed to agents
- [ ] Log score + decision to incident record

### End-of-Day Check
POST all 3 demo alerts → they correlate into 1 incident → FP Gate scores it > 65 → `status = investigating`. ✓

---

## Day 3 — LangGraph Orchestrator + Evidence Agent

**Estimated effort:** ~10h  
**Goal:** A LangGraph graph wakes up for each `investigating` incident and fetches mocked evidence in a controlled loop with a hard cost/latency guard.

### Technology

| Tool | Purpose |
|---|---|
| **LangGraph** | Stateful agent orchestration — cycles, conditionals, state management |
| **LangChain (langchain-openai)** | LLM abstraction layer, message formatting — configured against OpenRouter's endpoint, not Anthropic's |
| **Claude Sonnet 5** (`anthropic/claude-sonnet-5` via OpenRouter) | Orchestrator reasoning — deciding which connectors to query next |
| **Python dataclasses / Pydantic** | Evidence item schema with trust metadata |

### Tasks

**LangGraph Orchestrator**
- [ ] `pip install langgraph langchain-openai` — `ChatOpenAI` pointed at `base_url="https://openrouter.ai/api/v1"` with `OPENROUTER_API_KEY`, model `anthropic/claude-sonnet-5` (see `app/llm.py`)
- [ ] Define graph state: `{incident, evidence[], iteration, guard_triggered}`
- [ ] Create nodes: `plan_investigation` → `fetch_evidence` → `check_enough` → conditional edge
- [ ] Conditional edge: if `iteration >= 5` OR evidence sufficient → exit. Otherwise loop back.
- [ ] Wrap the whole graph run in a 90-second timeout. On timeout: set `guard_triggered=True`, emit `INSUFFICIENT_EVIDENCE`, proceed with what exists — never hang.

**Evidence Agent — mocked connectors** *(addresses Gap 2 and Gap 4 architecturally)*
- [ ] Build connector interface: `fetch(connector_name, query)` → `{data, source, connector, confidence: float, fetched_at}`
- [ ] Mock 4 connectors with hardcoded realistic JSON for the demo scenario:
  - `azure_monitor` → deployment logs showing misconfigured release at T-6min
  - `kubernetes` → pod restart events
  - `github_commits` → the specific commit that changed storage permissions
  - `iam_logs` → API calls to Azure OpenAI
- [ ] Tag every evidence item: `{source, connector, confidence: 0.0–1.0, fetched_at}` — this is the **Evidence Trust Layer**. Confidence scores: Monitor=0.95, K8s=0.9, GitHub=0.85
- [ ] Orchestrator picks connectors based on incident type via simple if/else — no magic needed for the POC

### End-of-Day Check
Trigger an `investigating` incident → LangGraph runs → 2–3 evidence fetches → loop exits cleanly → evidence array saved to DB with confidence scores. ✓

---

## Day 4 — Policy Agent (RAG) + Root Cause Agent

**Estimated effort:** ~8h  
**Goal:** The system retrieves relevant compliance policies and produces a root cause that cites specific evidence IDs.

### Technology

| Tool | Purpose |
|---|---|
| **ChromaDB** | Local vector database — no server, runs in-process via Docker |
| **LangChain** | Document chunking, embedding pipeline, retrieval chain |
| **ChromaDB built-in embeddings** (all-MiniLM-L6-v2, local, in-process) | Embed policy chunks for semantic retrieval — no external API key required |
| **Claude Sonnet 5** (`anthropic/claude-sonnet-5` via OpenRouter) | Root Cause Agent — structured JSON reasoning with citations |
| **Pydantic** | Validate and parse LLM JSON output — retry on malformed response |

### Tasks

**Policy Agent — lightweight RAG**
- [ ] Create `policies/` folder with 5 markdown files: `GDPR.md`, `SOC2.md`, `ISO27001.md`, `HIPAA.md`, `internal_ai_policy.md` (~300 words each, realistic content)
- [ ] Use ChromaDB: chunk → embed → index all 5 files
- [ ] `retrieve_policies(incident_summary)` → returns top 3 relevant snippets as `[{policy_id, title, excerpt, relevance_score}]`
- [ ] Test: `PublicStorageBucket` incident should surface GDPR Art. 32 + SOC2 CC6

**Root Cause Agent** *(fully addresses Gap 2)*
- [ ] Structured prompt: system = senior security analyst persona; user = `{timeline, evidence[], policies[]}`
- [ ] Require JSON output: `{root_cause, confidence, evidence_ids_cited[], alternative_hypotheses[], gdpr_flag}`
- [ ] Instruction in prompt: any evidence with `confidence < 0.5` must be explicitly flagged as `"low_confidence_source"` in the output
- [ ] Validate output with Pydantic — if LLM returns malformed JSON, retry once then fail gracefully
- [ ] Save to `incidents.root_cause` as JSONB

### End-of-Day Check
Full pipeline runs: correlate → gate → orchestrate → evidence → policies → root cause JSON with `evidence_ids_cited` populated. ✓

---

## Day 5 — Risk Assessment + Remediation Planner

**Estimated effort:** ~6h  
**Goal:** Every investigated incident gets a risk score and a stepwise remediation plan. Nothing executes automatically — ever.

### Technology

| Tool | Purpose |
|---|---|
| **Claude Sonnet 5** (`anthropic/claude-sonnet-5` via OpenRouter) | Generate executive risk narrative and remediation plan steps |
| **PostgreSQL JSONB** | Store structured risk + remediation output as flexible JSON columns |
| **Pydantic** | Enforce output schemas for both risk and remediation models |
| **Pure Python** | Deterministic base scoring — fast, auditable, no LLM dependency |

### Tasks

**Risk Assessment**
- [ ] Deterministic scoring first (no LLM): `severity_weight + correlated_count + gdpr_flag + affected_resources_count` → score 0–100
- [ ] LLM generates a 2-sentence executive narrative: "What happened and why does it matter to the business?" — non-technical language
- [ ] Output schema: `{severity: Critical|High|Medium|Low, business_impact, compliance_impact, affected_estimate, gdpr_flag, score}`
- [ ] Store in incidents table

**Remediation Planner**
- [ ] Prompt includes: root cause + risk assessment + top policy hits + runbook excerpts
- [ ] Output schema: `{steps: [{step_number, action, owner, priority, estimated_time, requires_human_approval}]}`
- [ ] Hard prompt constraint: *"Never include executable code, CLI commands, or SDK calls. Produce human-readable action descriptions only."*
- [ ] `requires_human_approval: true` hardcoded in the serializer on every step — not left to the LLM
- [ ] Store plan as JSONB

### End-of-Day Check
One incident in DB has: timeline → evidence with trust scores → policy hits → root cause with citations → risk score → remediation plan with approval flags. Full pipeline complete. ✓

---

## Day 6 — Dashboard UI + Report Generator

**Estimated effort:** ~10h  
**Goal:** Judges can see the full investigation in a browser. One button downloads a PDF. Record your demo video today.

### Technology

| Tool | Purpose |
|---|---|
| **Next.js 14** | React framework — file-based routing, API routes for BFF layer |
| **Tailwind CSS** | Utility-first styling — fast to build, consistent design |
| **React** | Component model for tabbed incident detail view |
| **reportlab** | Pure-Python PDF generation — no headless browser needed |
| **FastAPI** | `GET /api/incidents/{id}/report` endpoint streams the PDF |
| **Vercel** | Frontend deployment (free tier, one push) |

### Tasks

**Analyst Dashboard**
- [ ] Incident list: table with severity badge, FP score, status pill (`parked` / `queued` / `investigating` / `complete`), timestamp
- [ ] Incident detail — 6 tabs:
  - **Timeline** — chronological event list
  - **Evidence** — table with source, connector, confidence score bar, data preview
  - **Policies** — cards showing matched policies with relevance scores
  - **Root Cause** — cited evidence IDs highlighted, confidence score, alternative hypotheses
  - **Risk** — severity badge, business impact narrative, GDPR flag
  - **Remediation** — step cards with owner, priority, "Mark Approved" button (UI state only — no execution)
- [ ] Show FP Gate decision prominently: score + decision reason
- [ ] Auto-poll `GET /api/incidents` every 5 seconds to show live status changes as pipeline progresses

**Report Generator**
- [ ] `GET /api/incidents/{id}/report` endpoint returns a PDF stream
- [ ] Report sections: Executive Summary, Timeline, Evidence Table (with confidence scores), Policies Violated, Root Cause, Risk Score, Remediation Steps
- [ ] Confidence scores visible in evidence table — **this is what judges remember**
- [ ] Add `SecOpsMeshAI POC` header and generation timestamp
- [ ] "Download Report" button in UI triggers this endpoint

### Demo Script *(write this down and practice it)*

1. Open dashboard — show empty incident list
2. Run `curl` in a visible terminal — paste the demo alert JSON
3. Watch the incident appear, status flip to `investigating`
4. Click in — walk the tabs: Evidence (show confidence scores), Root Cause (show cited IDs), Risk (show GDPR flag), Remediation (show approval buttons)
5. Hit **Download Report** — open the PDF
6. Done. ~90 seconds of live action.

### End-of-Day Check
Dashboard running at `localhost:3000` → full investigation visible in UI → PDF downloads → demo script rehearsed at least once. ✓

---

## Day 7 — Polish, Deploy & Submit

**Estimated effort:** ~6h  
**Goal:** A stranger can clone your repo and run it in under 5 minutes. Judges can evaluate it without asking you anything.

### Technology

| Tool | Purpose |
|---|---|
| **Railway** | Backend deployment — free tier, PostgreSQL included, one-click deploy from GitHub |
| **Vercel** | Frontend deployment — auto-deploys on push to main |
| **Loom** | 3-minute demo video — no editing required, one clean take |
| **GitHub Actions** | Optional: CI that runs `docker-compose up` + curl smoke test on every push |

### Tasks

**Morning — Hardening**
- [ ] Test `docker-compose up` from a completely clean machine — fix everything that breaks
- [ ] Write `seed.py`: one command that inserts the full demo incident and runs the pipeline automatically
- [ ] Handle failure modes: LLM timeout → show "Investigation in progress" in UI, not a 500; DB down → `/health` returns 503 clearly
- [ ] Final `.env.example` — every required key documented with a comment explaining what it is

**Afternoon — Deploy**
- [ ] Deploy backend to Railway (free tier)
- [ ] Deploy frontend to Vercel
- [ ] Test live URL end-to-end using `seed.py` against the deployed backend
- [ ] Add live demo link to the top of the README

**Evening — Submission Assets**
- [ ] Record 3-minute Loom using the Day 6 demo script — one clean take, no edits needed
- [ ] Write one-page write-up: problem, architecture choices, what's real vs. mocked, the 4 gaps addressed, what Phase 2 looks like
- [ ] Build 5-slide deck: Problem → Architecture diagram → Live demo screenshot → How the 4 gaps are fixed → Roadmap to production
- [ ] README final pass: what it does, one-command setup, architecture overview, tech stack table, known limitations (be honest — judges respect it)
- [ ] **Submit. Do not add features after this point.**

### End-of-Day Check
Live URL working + 3-min video uploaded + GitHub repo public and clean + all submission assets ready. ✓

---

## Full Tech Stack Summary

| Layer | Choice | Why |
|---|---|---|
| Backend | FastAPI + Python | Fast to write, async, great for agent pipelines |
| LLM access | OpenRouter → Claude Sonnet 5 (`anthropic/claude-sonnet-5`) | Single OpenAI-compatible gateway/key; best structured JSON output, reliable citation following |
| Orchestration | LangGraph | Native stateful agent loops, built-in cycle detection |
| RAG / Vector DB | ChromaDB (local) | Zero infrastructure, runs in Docker, Python-native |
| Database | PostgreSQL + JSONB | Structured incidents + flexible agent output storage |
| Queue | Redis | Status updates without over-engineering |
| Frontend | Next.js + Tailwind CSS | Fast UI, great for tabbed layouts, deploys free on Vercel |
| PDF | reportlab | Pure Python, no browser/headless dependency |
| Deploy — Backend | Railway | Free tier, PostgreSQL included, GitHub-linked deploys |
| Deploy — Frontend | Vercel | Free tier, auto-deploy on push |

---

## Gaps Addressed in This POC

| Gap | Where It's Fixed |
|---|---|
| **Gap 1 — No FP Gate** | Day 2: rule-based confidence scoring parks noise before any LLM runs |
| **Gap 2 — Agent Trust & Provenance** | Day 3: every evidence item tagged `{source, connector, confidence, fetched_at}`; Day 4: Root Cause Agent must cite evidence IDs and flag low-confidence sources |
| **Gap 3 — Unbounded Cost/Latency** | Day 3: `MAX_ITERATIONS=5` hard cap + 90-second timeout with graceful `INSUFFICIENT_EVIDENCE` exit |
| **Gap 4 — Credential Blast Radius** | Day 3: connector interface is isolated per-connector (one function per source); in production each maps to one scoped token — show this in the architecture slide |

---

## What to Say When Judges Ask "What's Mocked?"

Be direct — it shows engineering judgment:

> *"The 4 evidence connectors return hardcoded realistic data for this scenario. In production, each would be a thin API wrapper with its own scoped read-only credential. The agent logic, LangGraph orchestration, RAG pipeline, LLM reasoning, evidence trust scoring, and human approval workflow are all real and running live."*

That answer wins more points than pretending everything is real.

---

## Submission Checklist

- [ ] Public GitHub repo with README, architecture diagram, and `docker-compose` setup
- [ ] 3-minute demo video: paste raw alert → agents investigate → report downloads
- [ ] One-page write-up: problem, what's real vs. mocked, gaps addressed, roadmap
- [ ] 5-slide deck: problem → architecture → demo screenshot → gap fixes → next steps
- [ ] Live demo URL (Vercel + Railway) or Docker Compose for local judging

---

*SecOpsMeshAI Hackathon POC · v1.0 · July 2026*