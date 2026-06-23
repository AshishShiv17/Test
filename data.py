"""
exporter.py
Converts parsed telemetry dicts into versioned JSON files inside /telemetry.
"""

from __future__ import annotations
import json
import logging
import os
from pathlib import Path
from typing import Dict, Any

logger = logging.getLogger(__name__)

_TELEMETRY_DIR = Path(os.getenv("TELEMETRY_DIR", "telemetry"))


def export(trace: Dict[str, Any], telemetry_dir: Path | None = None) -> Path:
    """
    Write a telemetry dict to a JSON file.

    The file is named  trace_<trace_id>.json  and stored in `telemetry_dir`.

    Args:
        trace:         Parsed telemetry dict (must have a 'trace_id' key).
        telemetry_dir: Override directory; defaults to $TELEMETRY_DIR env var.

    Returns:
        Absolute Path of the written file.
    """
    out_dir = telemetry_dir or _TELEMETRY_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    trace_id = trace.get("trace_id", "unknown")
    file_path = out_dir / f"trace_{trace_id}.json"

    with open(file_path, "w", encoding="utf-8") as fh:
        json.dump(trace, fh, indent=2, default=str)

    logger.info(f"[SDK] Trace exported → {file_path.resolve()}")
    return file_path
"""
instrument.py
Entry point for the SDK. Call instrument() once at the start of any agent project
to enable LangSmith tracing and automatic JSON export.
"""

import os
import logging
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)


def instrument(project: str | None = None):
    """
    Bootstrap observability for an OpenAI Agents SDK project.

    - Sets LangSmith environment variables.
    - Confirms configuration is in place.

    Args:
        project: Optional LangSmith project name override.
                 Falls back to LANGCHAIN_PROJECT env var.
    """
    _configure_langsmith(project)
    logger.info("Observability SDK initialised. LangSmith tracing is active.")


def _configure_langsmith(project: str | None):
    """Push LangSmith env vars so the langsmith SDK picks them up automatically."""
    if project:
        os.environ["LANGCHAIN_PROJECT"] = project

    required = {
        "LANGCHAIN_TRACING_V2": os.getenv("LANGCHAIN_TRACING_V2", "true"),
        "LANGCHAIN_ENDPOINT": os.getenv("LANGCHAIN_ENDPOINT", "https://api.smith.langchain.com"),
        "LANGCHAIN_API_KEY": os.getenv("LANGCHAIN_API_KEY", ""),
        "LANGCHAIN_PROJECT": os.getenv("LANGCHAIN_PROJECT", "agent-observability"),
    }

    for key, value in required.items():
        os.environ.setdefault(key, value)

    if not os.environ.get("LANGCHAIN_API_KEY"):
        logger.warning(
            "LANGCHAIN_API_KEY is not set. Traces will NOT be sent to LangSmith. "
            "Add it to your .env file."
        )
    else:
        logger.info(
            f"LangSmith project: {os.environ['LANGCHAIN_PROJECT']} | "
            f"endpoint: {os.environ['LANGCHAIN_ENDPOINT']}"
        )
"""
parser.py
Extracts structured telemetry fields from an OpenAI Agents SDK run result.
"""

from __future__ import annotations
import logging
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


def parse_run_result(
    run_result: Any,
    agent_name: str = "UnknownAgent",
    trace_id: str | None = None,
    start_time: str | None = None,
    end_time: str | None = None,
    latency: float = 0.0,
) -> Dict[str, Any]:
    """
    Parse an OpenAI Agents SDK RunResult into a standardised telemetry dict.

    Args:
        run_result:  The object returned by Runner.run() / Runner.run_sync().
        agent_name:  Human-readable name of the agent.
        trace_id:    Unique ID for this run (generated externally).
        start_time:  ISO-8601 string of when the run started.
        end_time:    ISO-8601 string of when the run ended.
        latency:     Wall-clock seconds elapsed.

    Returns:
        A flat dict ready to be serialised to JSON.
    """
    tool_calls, tools_used = _extract_tool_info(run_result)
    llm_calls = _extract_llm_calls(run_result)
    status = _extract_status(run_result)
    output = _extract_output(run_result)

    return {
        "trace_id": trace_id or "unknown",
        "agent": agent_name,
        "status": status,
        "start_time": start_time,
        "end_time": end_time,
        "latency": round(latency, 4),
        "llm_calls": llm_calls,
        "tool_calls": tool_calls,
        "tools": tools_used,
        "output": output,
    }


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _extract_tool_info(run_result: Any):
    """Return (tool_call_count, list_of_tool_names)."""
    tools: List[str] = []
    try:
        for item in getattr(run_result, "new_items", []):
            item_type = getattr(item, "type", None) or type(item).__name__
            if "tool" in str(item_type).lower():
                name = getattr(item, "name", None) or getattr(item, "tool_name", "UnknownTool")
                tools.append(name)
    except Exception as exc:
        logger.debug(f"Could not extract tool info: {exc}")
    return len(tools), list(dict.fromkeys(tools))  # deduplicated, order preserved


def _extract_llm_calls(run_result: Any) -> int:
    """Count message output items as a proxy for LLM calls."""
    try:
        return sum(
            1
            for item in getattr(run_result, "new_items", [])
            if "message" in str(getattr(item, "type", "")).lower()
               or "response" in type(item).__name__.lower()
        )
    except Exception:
        return 1  # assume at least one call


def _extract_status(run_result: Any) -> str:
    try:
        if hasattr(run_result, "final_output") and run_result.final_output:
            return "success"
        return "failure"
    except Exception:
        return "unknown"


def _extract_output(run_result: Any) -> str:
    try:
        return str(getattr(run_result, "final_output", ""))[:500]
    except Exception:
        return ""
"""
telemetry.py
High-level helper that wraps an agent run, captures timing, parses the result,
and exports a JSON trace — all in one call.

Usage:
    from sdk.telemetry import run_with_telemetry
    from agents import Runner

    result = await run_with_telemetry(
        runner_coro=Runner.run(agent, prompt),
        agent_name="MyAgent",
    )
"""

from __future__ import annotations
import asyncio
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Coroutine

from sdk.parser import parse_run_result
from sdk.exporter import export

logger = logging.getLogger(__name__)


async def run_with_telemetry(
    runner_coro: Coroutine,
    agent_name: str = "Agent",
) -> Any:
    """
    Await an OpenAI Agents SDK coroutine, measure latency, parse the result,
    and write a JSON trace file.

    Args:
        runner_coro: Awaitable returned by  Runner.run(agent, prompt).
        agent_name:  Label for this agent in the telemetry output.

    Returns:
        The original RunResult so callers can still use it normally.
    """
    trace_id = _new_trace_id()
    start_dt = datetime.now(timezone.utc)
    t0 = time.perf_counter()

    run_result = await runner_coro

    latency = time.perf_counter() - t0
    end_dt = datetime.now(timezone.utc)

    trace = parse_run_result(
        run_result=run_result,
        agent_name=agent_name,
        trace_id=trace_id,
        start_time=start_dt.isoformat(),
        end_time=end_dt.isoformat(),
        latency=latency,
    )

    export(trace)
    return run_result


def run_with_telemetry_sync(
    agent_name: str = "Agent",
) -> Callable:
    """
    Decorator for synchronous runner calls.

    Usage:
        @run_with_telemetry_sync(agent_name="MyAgent")
        def run_agent():
            return Runner.run_sync(agent, prompt)
    """
    def decorator(fn: Callable) -> Callable:
        def wrapper(*args, **kwargs):
            trace_id = _new_trace_id()
            start_dt = datetime.now(timezone.utc)
            t0 = time.perf_counter()

            run_result = fn(*args, **kwargs)

            latency = time.perf_counter() - t0
            end_dt = datetime.now(timezone.utc)

            trace = parse_run_result(
                run_result=run_result,
                agent_name=agent_name,
                trace_id=trace_id,
                start_time=start_dt.isoformat(),
                end_time=end_dt.isoformat(),
                latency=latency,
            )
            export(trace)
            return run_result
        return wrapper
    return decorator


def _new_trace_id() -> str:
    return uuid.uuid4().hex[:12]
