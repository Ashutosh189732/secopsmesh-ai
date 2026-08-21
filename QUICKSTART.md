# SecOpsMeshAI — 5-Minute Quickstart

**Goal:** Run the full demo end-to-end in under 5 minutes.

---

## Prerequisites

- **Python 3.11+** — Check: `python --version`
- **Node.js 18+** (for dashboard) — Check: `node --version`
- **OpenRouter API key** (free trial) — Get at: https://openrouter.ai/keys

---

## Step 1: Backend Setup (2 minutes)

```bash
# Clone (skip if already done)
git clone https://github.com/yourusername/secopsmesh-ai.git
cd secopsmesh-ai

# Create Python virtual environment
python -m venv .venv

# Activate virtual environment
# Windows Git Bash:
source .venv/Scripts/activate

# Windows cmd:
# .venv\Scripts\activate.bat

# Mac/Linux:
# source .venv/bin/activate

# Install dependencies (takes ~60 seconds)
pip install -r requirements.txt

# Configure environment
cp .env.example .env

# Edit .env with your favorite editor:
# - Set OPENROUTER_API_KEY=sk-or-v1-your-key-here
# - Leave DATABASE_URL as-is (SQLite default)

# Start backend
uvicorn app.main:app --reload
```

**Expected output:**
```
INFO:     Uvicorn running on http://127.0.0.1:8000 (Press CTRL+C to quit)
INFO:     Application startup complete.
```

**Verify:** Open http://127.0.0.1:8000/health in browser, should see:
```json
{"status": "healthy", "environment": "development"}
```

---

## Step 2: Frontend Setup (2 minutes, optional)

**Open a NEW terminal** (keep backend running in the first one):

```bash
cd secopsmesh-ai/frontend

# Install dependencies (takes ~90 seconds first time)
npm install

# Start development server
npm run dev
```

**Expected output:**
```
> frontend@1.0.0 dev
> next dev

  ▲ Next.js 14.x.x
  - Local:        http://localhost:3000
```

**Verify:** Open http://localhost:3000 in browser, should see empty incident list.

**If you skip this step:** You can still test via curl + API docs at http://127.0.0.1:8000/docs

---

## Step 3: Run Demo (1 minute)

### Option A: API-Only Demo (No Frontend)

```bash
# Health check
curl http://127.0.0.1:8000/health

# Post a noise signal (will be parked)
curl -X POST http://127.0.0.1:8000/api/signals \
  -H "Content-Type: application/json" \
  -d '{
    "signal_type": "UnauthorizedAPICall",
    "resource_name": "dev-sandbox-03",
    "severity": "low",
    "source": "endpoint_agent",
    "details": {"caller": "test-runner"}
  }'

# List incidents (should see one with status: parked)
curl http://127.0.0.1:8000/api/incidents | json_pp

# Post flagship demo scenario (three correlated signals)
curl -X POST http://127.0.0.1:8000/api/signals -H "Content-Type: application/json" -d '{"signal_type":"PublicStorageBucket","resource_name":"prod-analytics-exports","severity":"critical","source":"azure_monitor","details":{"bucket_acl":"public-read"}}'

curl -X POST http://127.0.0.1:8000/api/signals -H "Content-Type: application/json" -d '{"signal_type":"LargeDataUpload","resource_name":"prod-analytics-exports","severity":"high","source":"azure_monitor","details":{"size_gb":4.2,"file_name":"customer_export.csv"}}'

curl -X POST http://127.0.0.1:8000/api/signals -H "Content-Type: application/json" -d '{"signal_type":"UnauthorizedAPICall","resource_name":"prod-analytics-exports","severity":"medium","source":"iam_logs","details":{"caller":"svc-deploy-bot","api":"azure.openai.completions"}}'

# Wait 20-30 seconds for LLM pipeline to complete, then check results
sleep 25
curl http://127.0.0.1:8000/api/incidents | json_pp
```

**What to look for:**
- First incident: `status: "parked"`, `fp_score: 23`
- Second incident: `status: "analyzed"`, `fp_score: 110`, `correlated_count: 3`
- Evidence array with 2-3 items (confidence scores 0.85-0.95)
- Root cause with `gdpr_flag: true` and `evidence_ids_cited: ["ev1", "ev2", ...]`

---

### Option B: Dashboard Demo (If Frontend Running)

1. Open http://localhost:3000
2. Run the flagship scenario curls above (three `POST /api/signals` commands)
3. Watch dashboard auto-refresh every 5 seconds
4. Click into the `prod-analytics-exports` incident
5. Explore tabs: Timeline → Evidence → Policies → Root Cause → Risk → Remediation
6. Click "Download Report" → PDF opens

---

## Step 4: Presenter-Paced Demo (Optional)

**Best for live hackathon presentations:**

```bash
python demo/run_scenario.py 08_presenter_paced_escalation
```

**What happens:**
1. Script posts first signal (Key Vault enumeration, score 64 → `queued`)
2. Script **pauses and waits for you to press Enter**
3. Dashboard shows incident in `queued` status — talk about FP gate scoring
4. Press Enter when ready
5. Script posts second signal (bucket goes public, score jumps to 95 → `investigating`)
6. Watch status badge flip live, full LLM pipeline runs

**Perfect for controlling the narrative during judging.**

---

## Troubleshooting

### Backend won't start
```
ModuleNotFoundError: No module named 'fastapi'
```
**Fix:** Activate virtual environment first: `source .venv/Scripts/activate`

---

### Frontend build error
```
Error: Cannot find module 'next'
```
**Fix:** Run `npm install` in `frontend/` directory

---

### Evidence tab empty after 30+ seconds
**Possible causes:**
1. OPENROUTER_API_KEY not set or invalid
   - Check `.env` file exists and has `OPENROUTER_API_KEY=sk-or-v1-...`
   - Verify key at https://openrouter.ai/keys
2. OpenRouter API quota exhausted
   - Free trial: $5 credit, ~200 requests
   - Check usage: https://openrouter.ai/activity
3. Network firewall blocking OpenRouter
   - Try: `curl -H "Authorization: Bearer YOUR_KEY" https://openrouter.ai/api/v1/models`

**Check backend logs:**
```bash
# In terminal where uvicorn is running, look for:
WARNING orchestrator planner LLM call failed: ...
```

---

### PDF download fails
```
500 Internal Server Error
```
**Fix:** Ensure reportlab installed: `pip install reportlab`

---

### Dashboard shows "Could not reach API"
**Fixes:**
1. Check backend is running: `curl http://127.0.0.1:8000/health`
2. Check CORS: backend logs should NOT show CORS errors
3. Frontend `.env.local` (if exists) should NOT override `NEXT_PUBLIC_API_URL`
   - Default is `http://127.0.0.1:8000`, usually correct

---

## Next Steps

- **Read full README:** [README.md](README.md)
- **Demo script for presentations:** [DEMO_SCRIPT.md](DEMO_SCRIPT.md)
- **Pitch deck content:** [HACKATHON_PITCH.md](HACKATHON_PITCH.md)
- **All demo scenarios:** [demo/scenarios.md](demo/scenarios.md)
- **API documentation:** http://127.0.0.1:8000/docs (when backend running)

---

## Common Demo Flows

### For Judges (Show Everything Fast)
1. Start backend + frontend
2. Open dashboard in browser
3. Run flagship scenario (3 curls)
4. Wait 25 seconds
5. Click into incident, walk through all 6 tabs (30 seconds each)
6. Download PDF report

**Total time: 5-7 minutes**

---

### For Technical Deep Dive
1. Show code structure: `tree -L 2 app/`
2. Explain FP gate logic: `cat app/fp_gate.py | grep "def score"`
3. Explain orchestrator: `cat app/orchestrator/graph.py | head -50`
4. Run scenario with backend logs visible: show LLM calls in real-time
5. Open SQLite DB: `sqlite3 secopsmesh.db "SELECT id, status, fp_score FROM incidents;"`

**Total time: 10-15 minutes**

---

### For Non-Technical Audience
1. Start with problem statement: "SOC teams drown in 96% false positives"
2. Show dashboard with one `parked` incident: "This noise was stopped before any AI ran"
3. Run flagship scenario, watch it populate live
4. Open Evidence tab: "Every piece of data is tagged with where it came from"
5. Open Remediation tab: "Every action requires a human to approve it"
6. Download PDF: "This is what your incident response team gets"

**Total time: 3-5 minutes**

---

**Questions? Open an issue or reach out at your@email.com**
