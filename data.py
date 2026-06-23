"""
main.py
FastAPI application entry point.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routers import dashboard, telemetry
from app.config import settings

app = FastAPI(
    title="Agent Observability API",
    description="Observability dashboard for OpenAI Agents SDK with LangSmith tracing.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(dashboard.router, prefix="/dashboard", tags=["Dashboard"])
app.include_router(telemetry.router, prefix="/telemetry", tags=["Telemetry"])


@app.get("/", tags=["Health"])
def root():
    return {
        "status": "ok",
        "project": settings.LANGCHAIN_PROJECT,
        "environment": settings.APP_ENV,
    }


@app.get("/health", tags=["Health"])





"""
utils.py
Shared utility helpers for the FastAPI app.
"""

import json
import logging
from pathlib import Path
from typing import List, Dict, Any

logger = logging.getLogger(__name__)


def load_all_traces(telemetry_dir: Path) -> List[Dict[str, Any]]:
    """Load and return all trace JSON files from the telemetry directory."""
    traces = []
    if not telemetry_dir.exists():
        logger.warning(f"Telemetry directory '{telemetry_dir}' does not exist.")
        return traces

    for file in sorted(telemetry_dir.glob("trace_*.json")):
        try:
            with open(file, "r") as f:
                traces.append(json.load(f))
        except (json.JSONDecodeError, IOError) as e:
            logger.error(f"Failed to load trace file {file}: {e}")

    return traces


def load_trace_by_id(telemetry_dir: Path, trace_id: str) -> Dict[str, Any] | None:
    """Load a single trace file by trace_id."""
    for file in telemetry_dir.glob("trace_*.json"):
        try:
            with open(file, "r") as f:
                data = json.load(f)
                if data.get("trace_id") == trace_id:
                    return data
        except (json.JSONDecodeError, IOError):
            continue
    return None




"""
config.py
Loads all environment variables and exposes them as a typed Settings object.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()


class Settings:


    # ------------------------------------------------------------------
    # LangSmith
    # ------------------------------------------------------------------
    LANGCHAIN_TRACING_V2: str = os.getenv("LANGCHAIN_TRACING_V2", "true")
    LANGCHAIN_ENDPOINT: str = os.getenv("LANGCHAIN_ENDPOINT", "https://api.smith.langchain.com")
    LANGCHAIN_API_KEY: str = os.getenv("LANGCHAIN_API_KEY", "")
    LANGCHAIN_PROJECT: str = os.getenv("LANGCHAIN_PROJECT", "agent-observability")

    # ------------------------------------------------------------------
    # Application
    # ------------------------------------------------------------------
    APP_ENV: str = os.getenv("APP_ENV", "development")
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    TELEMETRY_DIR: Path = Path(os.getenv("TELEMETRY_DIR", "telemetry"))

    def validate(self):
        """Raise early if required keys are missing."""
        missing = []
        if not self.API_KEY:
            missing.append("API_KEY")
        if not self.LANGCHAIN_API_KEY:
            missing.append("LANGCHAIN_API_KEY")
        if missing:
            raise EnvironmentError(
                f"Missing required environment variables: {', '.join(missing)}. "
                "Please check your .env file."
            )


settings = Settings()

def health():
    return {"status": "healthy"}
