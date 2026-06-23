"""
langsmith_service.py
Reads and processes telemetry traces from local JSON files.
In a production setup this could also query the LangSmith REST API directly.
"""

from typing import List, Dict, Any, Optional
from app.config import settings
from app.utils import load_all_traces, load_trace_by_id


def get_all_traces() -> List[Dict[str, Any]]:
    """Return all available trace records from the telemetry directory."""
    return load_all_traces(settings.TELEMETRY_DIR)


def get_trace_by_id(trace_id: str) -> Optional[Dict[str, Any]]:
    """Return a single trace by its ID."""
    return load_trace_by_id(settings.TELEMETRY_DIR, trace_id)
