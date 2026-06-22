"""
Tests for the MCP server tools (app.mcp_server). Database access is mocked.
"""
import asyncio
from datetime import datetime
from decimal import Decimal
from uuid import UUID
from unittest.mock import patch


from app import mcp_server


def test_expected_tools_registered():
    tools = asyncio.run(mcp_server.mcp.list_tools())
    names = {t.name for t in tools}
    assert {"list_devices", "latest_reading", "reading_history", "aqi_status", "ask"} <= names


def test_jsonable_converts_db_types():
    out = mcp_server._jsonable({
        "t": datetime(2026, 4, 2, 18, 48),
        "d": Decimal("8.3"),
        "u": UUID(int=0),
        "nested": [Decimal("2"), {"x": datetime(2026, 1, 1)}],
    })
    assert out["t"] == "2026-04-02T18:48:00"
    assert out["d"] == 8.3
    assert isinstance(out["u"], str)
    assert out["nested"] == [2.0, {"x": "2026-01-01T00:00:00"}]


@patch("app.mcp_server.queries.list_devices")
@patch("app.mcp_server.get_db")
def test_list_devices_tool(mock_db, mock_q):
    mock_q.return_value = [{"device_id": "d1", "last_reading_at": datetime(2026, 1, 1)}]
    out = mcp_server.list_devices()
    assert out[0]["device_id"] == "d1"
    assert out[0]["last_reading_at"] == "2026-01-01T00:00:00"
    mock_db.return_value.close.assert_called_once()


@patch("app.mcp_server.queries.latest_reading", return_value=None)
@patch("app.mcp_server.get_db")
def test_aqi_status_no_readings(mock_db, mock_q):
    assert mcp_server.aqi_status("ghost") == {"device_id": "ghost", "status": "no readings"}


@patch("app.mcp_server.graph.run")
@patch("app.mcp_server.retrieval.resolve_device_id", return_value="airq-001")
@patch("app.mcp_server.get_db")
def test_ask_tool(mock_db, mock_resolve, mock_run):
    mock_run.return_value = {"answer": "Good.", "route": "specific", "meta": {}}
    out = mcp_server.ask("how is it?")
    assert out == {"answer": "Good.", "device_id": "airq-001", "route": "specific"}
