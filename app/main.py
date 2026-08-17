import threading
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.auth import require_api_key
from app.database import init_db
from app.orchestrator import worker
from app.routers import health, incidents, signals


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    # Re-queue incidents a previous process (crash or --reload restart) left
    # mid-investigation — the in-memory queue and worker thread die with it.
    worker.requeue_inflight()
    stop_event = threading.Event()
    worker.start(stop_event)
    yield
    stop_event.set()


app = FastAPI(title="SecOpsMeshAI POC", lifespan=lifespan)

# Day 6: the Next.js dashboard (localhost:3000) calls this API directly from
# the browser rather than through a same-origin proxy — needs CORS enabled.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# health stays open (load balancers / uptime checks hit it unauthenticated).
# The data endpoints require the API key when one is configured (no-op otherwise).
app.include_router(health.router)
app.include_router(signals.router, dependencies=[Depends(require_api_key)])
app.include_router(incidents.router, dependencies=[Depends(require_api_key)])
