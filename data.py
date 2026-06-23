"""
telemetry.py
FastAPI router for reading individual trace records.
Serves both local traces and live LangSmith traces.
"""

from fastapi import APIRouter, HTTPException, Query
from langsmith import Client

from app.config import settings
from app.services.langsmith_service import (
    get_all_traces,
    get_trace_by_id,
    fetch_runs_from_langsmith,
    _client,
)
from app.services.json_service import export_trace_to_json

router = APIRouter()


@router.get("/traces")
def list_traces(source: str = Query(default="local", enum=["local", "langsmith"])):
    """
    Return all telemetry trace records.
    - ?source=local      → reads from local JSON files (default)
    - ?source=langsmith  → fetches live from LangSmith API
    """
    if source == "langsmith":
        try:
            return fetch_runs_from_langsmith(limit=100)
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"LangSmith fetch failed: {e}")
    return get_all_traces()


@router.get("/traces/{trace_id}")
def get_trace(
    trace_id: str,
    source: str = Query(default="local", enum=["local", "langsmith"]),
):
    """
    Return a single trace record by trace_id.
    - ?source=local      → reads from local JSON file (default)
    - ?source=langsmith  → fetches live from LangSmith API
    """
    if source == "langsmith":
        try:
            run = _client.read_run(run_id=trace_id)
            if not run:
                raise HTTPException(status_code=404, detail=f"Trace '{trace_id}' not found on LangSmith.")
            return {
                "trace_id":   str(run.id),
                "name":       run.name,
                "run_type":   run.run_type,
                "inputs":     run.inputs or {},
                "outputs":    run.outputs or {},
                "error":      run.error,
                "start_time": run.start_time.isoformat() if run.start_time else None,
                "end_time":   run.end_time.isoformat() if run.end_time else None,
                "status":     "error" if run.error else "success",
                "tags":       run.tags or [],
            }
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"LangSmith fetch failed: {e}")

    trace = get_trace_by_id(trace_id)
    if not trace:
        raise HTTPException(status_code=404, detail=f"Trace '{trace_id}' not found.")
    return trace


@router.post("/traces")
def ingest_trace(trace_data: dict):
    """
    Accept a new trace payload, write it to local JSON,
    and push it to LangSmith in one shot.
    """
    if not trace_data.get("trace_id"):
        raise HTTPException(status_code=400, detail="'trace_id' is required.")
    try:
        file_path = export_trace_to_json(trace_data)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to ingest trace: {e}")
    return {"status": "ok", "file": str(file_path)}
"""
dashboard.py
FastAPI router for aggregated dashboard metrics.
Merges local telemetry + live LangSmith data.
"""

from collections import Counter
from fastapi import APIRouter, HTTPException
from app.services.dashboard_service import get_dashboard_summary
from app.services.langsmith_service import fetch_runs_from_langsmith
from app.services.json_service import export_trace_to_json

router = APIRouter()


@router.get("/summary")
def dashboard_summary():
    """Return aggregated metrics from local telemetry files."""
    try:
        return get_dashboard_summary()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Dashboard error: {e}")


@router.get("/summary/live")
def dashboard_summary_live():
    """
    Fetch latest runs directly from LangSmith and return aggregated metrics.
    Also syncs fetched runs into local telemetry for consistency.
    """
    try:
        runs = fetch_runs_from_langsmith(limit=100)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"LangSmith fetch failed: {e}")

    if not runs:
        return {
            "total_runs": 0,
            "success_count": 0,
            "failure_count": 0,
            "average_latency_seconds": 0,
            "total_llm_calls": 0,
            "total_tool_calls": 0,
            "most_used_tools": [],
            "source": "langsmith",
        }

    # Sync fetched runs into local JSON so local dashboard stays consistent
    for run in runs:
        try:
            export_trace_to_json(run)
        except Exception:
            pass

    total = len(runs)
    success = sum(1 for r in runs if r.get("status") == "success")
    failure = total - success
    latencies = [r.get("latency") or 0 for r in runs]
    avg_latency = round(sum(latencies) / total, 3) if total else 0

    tool_counter: Counter = Counter()
    for r in runs:
        for tool in r.get("tools", []):
            tool_counter[tool] += 1

    return {
        "total_runs": total,
        "success_count": success,
        "failure_count": failure,
        "average_latency_seconds": avg_latency,
        "total_llm_calls": sum(r.get("llm_calls", 0) for r in runs),
        "total_tool_calls": sum(r.get("tool_calls", 0) for r in runs),
        "most_used_tools": tool_counter.most_common(5),
        "source": "langsmith",
    }


@router.post("/sync")
def sync_from_langsmith():
    """
    Manually pull latest runs from LangSmith and write them
    to local telemetry JSON files.
    """
    try:
        runs = fetch_runs_from_langsmith(limit=200)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"LangSmith fetch failed: {e}")

    synced, failed = 0, 0
    for run in runs:
        try:
            export_trace_to_json(run)
            synced += 1
        except Exception:
            failed += 1

    return {"synced": synced, "failed": failed, "total_fetched": len(runs)}

"""
json_service.py
Handles export of telemetry data to JSON files and pushes to LangSmith.
"""

import json
import logging
from pathlib import Path
from typing import Dict, Any, List

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


def load_all_traces_from_json() -> List[Dict[str, Any]]:
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
"""
langsmith_service.py
Reads local telemetry traces AND pushes/fetches from the LangSmith REST API.
SSL verification handled via certifi or custom corp cert bundle.
"""

import logging
from datetime import datetime
from typing import List, Dict, Any, Optional

import certifi
import httpx
from langsmith import Client

from app.config import settings
from app.utils import load_all_traces, load_trace_by_id

logger = logging.getLogger(__name__)


def _build_client() -> Client:
    """
    Build a LangSmith client with correct SSL verification.
    - Uses corp cert bundle if SSL_CERT_FILE is set in config.
    - Falls back to certifi's trusted CA bundle.
    - Respects LANGSMITH_VERIFY_SSL=false for local dev only.
    """
    if not settings.LANGSMITH_VERIFY_SSL:
        logger.warning("SSL verification is DISABLED. Do not use this in production.")
        verify: Any = False
    elif settings.SSL_CERT_FILE:
        logger.info(f"Using custom SSL cert bundle: {settings.SSL_CERT_FILE}")
        verify = settings.SSL_CERT_FILE
    else:
        verify = certifi.where()

    return Client(
        api_key=settings.LANGCHAIN_API_KEY,
        http_client=httpx.Client(verify=verify),
    )


_client = _build_client()


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
        logger.warning(f"Invalid run_type '{run_type}', defaulting to 'chain'.")
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
                "latency":    trace_data.get("latency", 0),
                "status":     trace_data.get("status", "unknown"),
                "llm_calls":  trace_data.get("llm_calls", 0),
                "tool_calls": trace_data.get("tool_calls", 0),
                "tools":      trace_data.get("tools", []),
                **(trace_data.get("metadata") or {}),
            }
        },
        project_name=settings.LANGCHAIN_PROJECT,
    )
    logger.info(f"Trace '{trace_data.get('trace_id')}' pushed to LangSmith.")


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
    project = settings.LANGCHAIN_PROJECT

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
            "trace_id":   str(run.id),
            "name":       run.name,
            "run_type":   run.run_type,
            "inputs":     run.inputs or {},
            "outputs":    run.outputs or {},
            "error":      run.error,
            "start_time": run.start_time.isoformat() if run.start_time else None,
            "end_time":   run.end_time.isoformat() if run.end_time else None,
            "status":     "error" if run.error else "success",
            "tags":       run.tags or [],
            "tools":      [],
            "llm_calls":  0,
            "tool_calls": 0,
            "latency":    0,
        })

    logger.info(f"Fetched {len(results)} runs from LangSmith project '{project}'.")
    return results
