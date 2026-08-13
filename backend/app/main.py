"""
ATLAS — FastAPI application entry point.

Registers all Phase 7 API routers and configures CORS for local frontend
development.  The /health endpoint is retained from the Phase 0 skeleton.

Router registration order:
  telemetry — SSE stream + snapshot
  analysis  — analytics + risk status
  decision  — decision options + what-if
  copilot   — operator Q&A
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.app.api import analysis, copilot, decision, telemetry

app = FastAPI(
    title="ATLAS",
    description="Autonomous Telemetry, Learning, Analytics & Support — Mission Control Decision Support",
    version="0.1.0",
)

# CORS for local frontend development (Vite default port 5173)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Phase 7 routers
app.include_router(telemetry.router)
app.include_router(analysis.router)
app.include_router(decision.router)
app.include_router(copilot.router)


@app.get("/health")
async def health_check():
    """Liveness check — confirms the backend is running."""
    return {"status": "ok", "service": "ATLAS"}
