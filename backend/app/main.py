"""
ATLAS — FastAPI application entry point.

Skeleton only — no routes implemented.
Routes will be registered in Phase 7 (FastAPI Backend Integration).
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

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


@app.get("/health")
async def health_check():
    """Liveness check — confirms the backend is running."""
    return {"status": "ok", "service": "ATLAS"}
