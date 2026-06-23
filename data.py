"""
dashboard_service.py
Aggregates telemetry across all runs and returns dashboard-ready metrics.
"""

from collections import Counter
from typing import Dict, Any

from app.utils import load_all_traces
from app.config import settings


def get_dashboard_summary() -> Dict[str, Any]:
    traces = load_all_traces(settings.TELEMETRY_DIR)

    if not traces:
        return {
            "total_runs": 0,
            "success_count": 0,
            "failure_count": 0,
            "average_latency_seconds": 0,
            "total_llm_calls": 0,
            "total_tool_calls": 0,
            "most_used_tools": [],
        }

    total = len(traces)
    success = sum(1 for t in traces if t.get("status") == "success")
    failure = total - success

    latencies = [t.get("latency", 0) for t in traces]
    avg_latency = round(sum(latencies) / total, 3)

    total_llm = sum(t.get("llm_calls", 0) for t in traces)
    total_tools = sum(t.get("tool_calls", 0) for t in traces)

    tool_counter: Counter = Counter()
    for t in traces:
        for tool in t.get("tools", []):
            tool_counter[tool] += 1

    return {
        "total_runs": total,
        "success_count": success,
        "failure_count": failure,
        "average_latency_seconds": avg_latency,
        "total_llm_calls": total_llm,
        "total_tool_calls": total_tools,
        "most_used_tools": tool_counter.most_common(5),
    }
