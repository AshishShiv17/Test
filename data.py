"""
json_service.py
Handles export of telemetry data to JSON files.
Used by the FastAPI layer if export is triggered via API.
"""

import json
import logging
from pathlib import Path
from typing import Dict, Any

from app.config import settings

logger = logging.getLogger(__name__)


def export_trace_to_json(trace_data: Dict[str, Any]) -> Path:
    """
    Persist a trace dictionary to a JSON file inside the telemetry directory.

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

    logger.info(f"Trace exported → {file_path}")
    return file_path
