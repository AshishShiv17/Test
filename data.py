"""
dashboard.py
FastAPI router for aggregated dashboard metrics.
Merges local telemetry + live LangSmith data.
"""

from fastapi import APIRouter, HTTPException
from app.services.dashboard_service import get_dashboard_summary
from app.services.langsmith_service import fetch_runs_from_langsmith
from app.services.json_service import export_trace_to_json

router = APIRouter()


@router.get("/summary")
def dashboard_summary():
    """
    Returns aggregated metrics across all agent runs from local telemetry.
    """
    try:
        return get_dashboard_summary()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Dashboard error: {e}")


@router.get("/summary/live")
def dashboard_summary_live():
    """
    Fetches latest runs directly from LangSmith and returns aggregated metrics.
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

    # Sync fetched runs into local JSON so local dashboard stays up to date
    for run in runs:
        try:
            export_trace_to_json(run)
        except Exception:
            pass  # don't fail the response if a single sync write fails

    total = len(runs)
    success = sum(1 for r in runs if r.get("status") == "success")
    failure = total - success
    latencies = [r.get("latency") or 0 for r in runs]
    avg_latency = round(sum(latencies) / total, 3) if total else 0

    from collections import Counter
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
    to local telemetry JSON files. Call this to force a sync.
    """
    try:
        runs = fetch_runs_from_langsmith(limit=200)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"LangSmith fetch failed: {e}")

    synced = 0
    failed = 0
    for run in runs:
        try:
            export_trace_to_json(run)
            synced += 1
        except Exception:
            failed += 1

    return {
        "synced": synced,
        "failed": failed,
        "total_fetched": len(runs),
    }



"""
telemetry.py
FastAPI router for reading individual trace records.
Serves both local traces and live LangSmith traces.
"""

from fastapi import APIRouter, HTTPException, Query
from app.services.langsmith_service import (
    get_all_traces,
    get_trace_by_id,
    fetch_runs_from_langsmith,
    push_trace_to_langsmith,
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
            from langsmith import Client
            from app.config import settings

            client = Client()
            run = client.read_run(run_id=trace_id)
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
        file_path = export_trace_to_json(trace_data)   # writes local + pushes to LangSmith
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to ingest trace: {e}")

    return {"status": "ok", "file": str(file_path)}
