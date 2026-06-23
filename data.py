"""
langsmith_service.py
Reads local telemetry traces AND pushes/fetches from the LangSmith REST API.
"""

import logging
from datetime import datetime
from typing import List, Dict, Any, Optional

from langsmith import Client

from app.config import settings
from app.utils import load_all_traces, load_trace_by_id

logger = logging.getLogger(__name__)

# Client auto-reads LANGCHAIN_API_KEY from env
_client = Client()


# ── Local trace helpers ────────────────────────────────────────────────────────

def get_all_traces() -> List[Dict[str, Any]]:
    """Return all available trace records from the local telemetry directory."""
    return load_all_traces(settings.TELEMETRY_DIR)


def get_trace_by_id(trace_id: str) -> Optional[Dict[str, Any]]:
    """Return a single trace by its ID from local telemetry directory."""
    return load_trace_by_id(settings.TELEMETRY_DIR, trace_id)


# ── LangSmith push ─────────────────────────────────────────────────────────────

def push_trace_to_langsmith(trace_data: Dict[str, Any]) -> None:
    """
    Push a local trace dict to LangSmith as a Run.

    Expected keys in trace_data:
        trace_id        str       unique identifier
        name            str       run label shown in LangSmith UI
        run_type        str       one of: "llm", "chain", "tool", "retriever"
        inputs          dict      prompt / input payload
        outputs         dict      model response / output payload
        error           str|None  error message if run failed
        start_time      str|None  ISO-8601 datetime string
        end_time        str|None  ISO-8601 datetime string
        latency         float     seconds
        status          str       "success" | "error"
        llm_calls       int       number of LLM calls in this run
        tool_calls      int       number of tool calls in this run
        tools           list[str] tool names used
        tags            list[str] optional labels
        metadata        dict      any extra key/value pairs
    """
    def _parse_dt(value: Any) -> Optional[datetime]:
        if not value:
            return None
        if isinstance(value, datetime):
            return value
        try:
            return datetime.fromisoformat(str(value))
        except ValueError:
            logger.warning(f"Could not parse datetime: {value!r}")
            return None

    run_type = trace_data.get("run_type", "chain")
    valid_run_types = {"llm", "chain", "tool", "retriever"}
    if run_type not in valid_run_types:
        logger.warning(
            f"Invalid run_type '{run_type}', defaulting to 'chain'.")
        run_type = "chain"

    _client.create_run(
        id=trace_data.get("trace_id"),
        name=trace_data.get("name", "unnamed-run"),
        run_type=run_type,
        inputs=trace_data.get("inputs") or {},
        outputs=trace_data.get("outputs") or {},
        error=trace_data.get("error"),
        start_time=_parse_dt(trace_data.get("start_time")),
        end_time=_parse_dt(trace_data.get("end_time")),
        tags=trace_data.get("tags") or [],
        extra={
            "metadata": {
                "latency":     trace_data.get("latency", 0),
                "status":      trace_data.get("status", "unknown"),
                "llm_calls":   trace_data.get("llm_calls", 0),
                "tool_calls":  trace_data.get("tool_calls", 0),
                "tools":       trace_data.get("tools", []),
                **(trace_data.get("metadata") or {}),
            }
        },
        project_name=getattr(settings, "LANGCHAIN_PROJECT", "default"),
    )


# ── LangSmith fetch ────────────────────────────────────────────────────────────

def fetch_runs_from_langsmith(
    limit: int = 100,
    run_type: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Fetch recent runs from LangSmith and return them as plain dicts.

    Args:
        limit:    Max number of runs to retrieve.
        run_type: Optional filter — "llm", "chain", "tool", "retriever".

    Returns:
        List of run dicts normalised to the same shape as local traces.
    """
    project = getattr(settings, "LANGCHAIN_PROJECT", "default")

    try:
        runs = _client.list_runs(
            project_name=project,
            run_type=run_type,
            limit=limit,
        )
    except Exception as e:
        logger.error(f"Failed to fetch runs from LangSmith: {e}")
        return []

    results = []
    for run in runs:
        results.append({
            "trace_id":    str(run.id),
            "name":        run.name,
            "run_type":    run.run_type,
            "inputs":      run.inputs or {},
            "outputs":     run.outputs or {},
            "error":       run.error,
            "start_time":  run.start_time.isoformat() if run.start_time else None,
            "end_time":    run.end_time.isoformat() if run.end_time else None,
            "latency":     run.total_tokens,   # replace with latency if your SDK exposes it
            "status":      "error" if run.error else "success",
            "tags":        run.tags or [],
        })

    logger.info(
        f"Fetched {len(results)} runs from LangSmith project '{project}'.")
    return results



"""
json_service.py
Handles export of telemetry data to JSON files and pushes to LangSmith.
"""

import json
import logging
from pathlib import Path
from typing import Dict, Any

from app.config import settings
from app.services.langsmith_service import push_trace_to_langsmith

logger = logging.getLogger(__name__)


def export_trace_to_json(trace_data: Dict[str, Any]) -> Path:
    """
    Persist a trace dictionary to a JSON file inside the telemetry directory,
    then push the same trace to LangSmith.

    Args:
        trace_data: Parsed telemetry dict (must contain 'trace_id').

    Returns:
        Path to the written file.
    """
    telemetry_dir: Path = settings.TELEMETRY_DIR
    telemetry_dir.mkdir(parents=True, exist_ok=True)

    trace_id = trace_data.get("trace_id", "unknown")
    file_path = telemetry_dir / f"trace_{trace_id}.json"

    with open(file_path, "w") as f:
        json.dump(trace_data, f, indent=2, default=str)

    logger.info(f"Trace exported locally → {file_path}")

    try:
        push_trace_to_langsmith(trace_data)
        logger.info(f"Trace '{trace_id}' pushed to LangSmith successfully.")
    except Exception as e:
        logger.warning(f"LangSmith push failed for trace '{trace_id}': {e}")

    return file_path


def load_trace_from_json(trace_id: str) -> Dict[str, Any]:
    """
    Load a single trace from local JSON by trace_id.

    Args:
        trace_id: The trace identifier.

    Returns:
        Parsed trace dict, or empty dict if not found.
    """
    file_path: Path = settings.TELEMETRY_DIR / f"trace_{trace_id}.json"

    if not file_path.exists():
        logger.warning(f"Trace file not found: {file_path}")
        return {}

    with open(file_path, "r") as f:
        data = json.load(f)

    logger.info(f"Trace '{trace_id}' loaded from {file_path}")
    return data


def load_all_traces_from_json() -> list[Dict[str, Any]]:
    """
    Load all trace JSON files from the telemetry directory.

    Returns:
        List of parsed trace dicts.
    """
    telemetry_dir: Path = settings.TELEMETRY_DIR

    if not telemetry_dir.exists():
        logger.warning(f"Telemetry directory does not exist: {telemetry_dir}")
        return []

    traces = []
    for file_path in sorted(telemetry_dir.glob("trace_*.json")):
        try:
            with open(file_path, "r") as f:
                traces.append(json.load(f))
        except Exception as e:
            logger.error(f"Failed to load {file_path}: {e}")

    logger.info(f"Loaded {len(traces)} traces from {telemetry_dir}")
    return traces
