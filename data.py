"""
test_agent.py
Smoke tests for the DummyAgent tools (no live API needed).
"""

from dummy_agent.tools import calculator


def test_calculator_basic():
    result = calculator("2 + 2")
    assert result == "4"


def test_calculator_multiplication():
    result = calculator("42 * 7")
    assert result == "294"


def test_calculator_invalid():
    result = calculator("import os")
    assert "Error" in result
"""
test_dashboard.py
Integration tests for the FastAPI dashboard endpoints.
"""

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def _write_trace(directory: Path, trace: dict):
    tid = trace["trace_id"]
    with open(directory / f"trace_{tid}.json", "w") as f:
        json.dump(trace, f)


def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"


def test_dashboard_summary_empty():
    with tempfile.TemporaryDirectory() as tmpdir:
        with patch("app.config.settings.TELEMETRY_DIR", Path(tmpdir)):
            response = client.get("/dashboard/summary")
    assert response.status_code == 200
    assert response.json()["total_runs"] == 0


def test_dashboard_summary_with_data():
    traces = [
        {"trace_id": "001", "agent": "A", "status": "success", "latency": 2.0,
         "llm_calls": 1, "tool_calls": 1, "tools": ["Search"]},
        {"trace_id": "002", "agent": "A", "status": "failure", "latency": 4.0,
         "llm_calls": 1, "tool_calls": 0, "tools": []},
    ]
    with tempfile.TemporaryDirectory() as tmpdir:
        tdir = Path(tmpdir)
        for t in traces:
            _write_trace(tdir, t)
        with patch("app.config.settings.TELEMETRY_DIR", tdir):
            response = client.get("/dashboard/summary")

    data = response.json()
    assert data["total_runs"] == 2
    assert data["success_count"] == 1
    assert data["failure_count"] == 1
    assert data["average_latency_seconds"] == 3.0
"""
test_sdk.py
Unit tests for SDK parser and exporter.
"""

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

from sdk.parser import parse_run_result
from sdk.exporter import export


def _mock_run_result(output: str = "Hello"):
    mock = MagicMock()
    mock.final_output = output
    mock.new_items = []
    return mock


def test_parse_run_result_success():
    result = _mock_run_result("Paris is the capital of France.")
    trace = parse_run_result(
        run_result=result,
        agent_name="TestAgent",
        trace_id="abc123",
        start_time="2024-01-01T00:00:00+00:00",
        end_time="2024-01-01T00:00:03+00:00",
        latency=3.0,
    )
    assert trace["agent"] == "TestAgent"
    assert trace["trace_id"] == "abc123"
    assert trace["status"] == "success"
    assert trace["latency"] == 3.0


def test_export_creates_file():
    trace = {
        "trace_id": "test001",
        "agent": "TestAgent",
        "status": "success",
        "latency": 1.5,
        "llm_calls": 1,
        "tool_calls": 0,
        "tools": [],
    }
    with tempfile.TemporaryDirectory() as tmpdir:
        path = export(trace, telemetry_dir=Path(tmpdir))
        assert path.exists()
        with open(path) as f:
            loaded = json.load(f)
        assert loaded["trace_id"] == "test001"
