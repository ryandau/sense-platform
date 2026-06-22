"""
Model Context Protocol (MCP) server for Sense Platform.

Exposes the sensor data as tools so MCP clients (e.g. Claude Desktop) can list
devices, read readings, and ask natural-language questions. Reuses the shared
query layer (app.queries) and the /ask graph (app.ai.graph).

Run over stdio (default, for local clients such as Claude Desktop):
    python -m app.mcp_server
Run over HTTP (for the optional compose service / a networked client):
    MCP_TRANSPORT=streamable-http python -m app.mcp_server
"""

import os
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from mcp.server.fastmcp import FastMCP

from app import config, queries
from app.ai import graph, retrieval
from app.config import get_db

mcp = FastMCP(
    "sense-platform",
    host=os.environ.get("MCP_HOST", "0.0.0.0"),
    port=int(os.environ.get("MCP_PORT", "8001")),
)


def _jsonable(v):
    """Convert query rows (datetime/Decimal/UUID) into JSON-serialisable values."""
    if isinstance(v, dict):
        return {k: _jsonable(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_jsonable(x) for x in v]
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    if isinstance(v, UUID):
        return str(v)
    return v


@mcp.tool()
def list_devices() -> list[dict]:
    """List registered devices with their reading counts and last-seen times."""
    conn = get_db()
    try:
        return _jsonable(queries.list_devices(conn))
    finally:
        conn.close()


@mcp.tool()
def latest_reading(device_id: str) -> dict | None:
    """Get the most recent reading for a device, including computed metrics."""
    conn = get_db()
    try:
        return _jsonable(queries.latest_reading(conn, device_id))
    finally:
        conn.close()


@mcp.tool()
def reading_history(device_id: str, limit: int = 100) -> list[dict]:
    """Get recent readings for a device, newest first (maximum 1000)."""
    conn = get_db()
    try:
        return _jsonable(queries.reading_history(conn, device_id, limit))
    finally:
        conn.close()


@mcp.tool()
def aqi_status(device_id: str) -> dict:
    """Get the current air-quality status (latest data and computed categories)."""
    conn = get_db()
    try:
        row = queries.latest_reading(conn, device_id)
    finally:
        conn.close()
    if not row:
        return {"device_id": device_id, "status": "no readings"}
    return _jsonable({
        "device_id": device_id,
        "recorded_at": row.get("recorded_at"),
        "data": row.get("data"),
        "computed": row.get("computed"),
    })


@mcp.tool()
def ask(question: str, device_id: str | None = None) -> dict:
    """Ask a natural-language question about the sensor data."""
    conn = get_db()
    try:
        resolved = retrieval.resolve_device_id(conn, device_id)
        if not resolved:
            return {"error": "no devices found"}
        result = graph.run(conn, question, resolved, 24)
    finally:
        conn.close()
    return {"answer": result["answer"], "device_id": resolved, "route": result["route"]}


def main():
    config.validate()  # same required-configuration check as the API
    mcp.run(transport=os.environ.get("MCP_TRANSPORT", "stdio"))


if __name__ == "__main__":
    main()
