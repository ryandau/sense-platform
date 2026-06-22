"""
Tests for the Sense Platform API endpoints.
Uses FastAPI TestClient with a mocked database. Config is env-based (no AWS);
required env keys are set in conftest.py before the app is imported.
"""
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from app.main import app
import app.main as mod
import app.config as config
from tests._breakpoints import seed_breakpoints

TEST_API_KEY = "test-api-key-12345"
client = TestClient(app)


# ── Health (no auth, no DB) ──────────────────────────────

def test_health():
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_validate_requires_ai_keys(monkeypatch):
    monkeypatch.setattr(config, "OPENAI_API_KEY", "")
    with pytest.raises(config.ConfigError):
        config.validate()


# ── Ingest (requires auth + DB) ──────────────────────────

def test_ingest_missing_api_key():
    resp = client.post("/ingest", json={"device_id": "test-001", "data": {"pm2_5": 8.0}})
    assert resp.status_code in (401, 403)


def test_ingest_invalid_api_key():
    resp = client.post(
        "/ingest",
        json={"device_id": "test-001", "data": {"pm2_5": 8.0}},
        headers={"X-API-Key": "wrong-key"},
    )
    assert resp.status_code == 403


@patch("app.main.generate_embedding", return_value=None)
@patch("app.main.get_db")
def test_ingest_success(mock_get_db, mock_embed):
    seed_breakpoints(mod)

    mock_cursor = MagicMock()
    mock_cursor.fetchone.side_effect = [
        {"id": "abc-123"},                                           # readings INSERT RETURNING id
        {"name": "Test Sensor", "timezone": "Australia/Brisbane"},   # device SELECT
    ]
    mock_cursor.fetchall.return_value = []                           # field meta query
    mock_conn = MagicMock()
    mock_conn.cursor.return_value.__enter__ = lambda s: mock_cursor
    mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    mock_conn.__enter__ = lambda s: mock_conn
    mock_conn.__exit__ = MagicMock(return_value=False)
    mock_get_db.return_value = mock_conn

    mod._field_meta_cache = None
    mod._field_meta_cache_ts = 0

    resp = client.post(
        "/ingest",
        json={
            "device_id": "test-001",
            "type_slug": "air_quality",
            "data": {"pm2_5": 8.0, "co2_ppm": 420},
        },
        headers={"X-API-Key": TEST_API_KEY},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["status"] == "accepted"
    assert body["reading_id"] == "abc-123"
    assert body["computed"]["aqi_category"] == "Good"
    assert body["computed"]["co2_status"] == "Good"
    assert "content" in body


def test_ingest_empty_data_rejected():
    resp = client.post(
        "/ingest",
        json={"device_id": "test-001", "data": {}},
        headers={"X-API-Key": TEST_API_KEY},
    )
    assert resp.status_code == 422


# ── Read endpoints (public, no auth) ─────────────────────

@patch("app.main.get_db")
def test_devices_list(mock_get_db):
    mock_cursor = MagicMock()
    mock_cursor.fetchall.return_value = [
        {"id": "1", "device_id": "sensor-001", "type_slug": "air_quality",
         "reading_count": 5, "last_reading_at": None},
    ]
    mock_conn = MagicMock()
    mock_conn.cursor.return_value.__enter__ = lambda s: mock_cursor
    mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    mock_get_db.return_value = mock_conn

    resp = client.get("/devices")
    assert resp.status_code == 200
    assert resp.json()[0]["device_id"] == "sensor-001"


@patch("app.main.get_db")
def test_device_latest(mock_get_db):
    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = {
        "id": "abc", "device_id": "sensor-001",
        "data": {"pm2_5": 8.0}, "computed": {"aqi": 33},
    }
    mock_conn = MagicMock()
    mock_conn.cursor.return_value.__enter__ = lambda s: mock_cursor
    mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    mock_get_db.return_value = mock_conn

    resp = client.get("/devices/sensor-001/latest")
    assert resp.status_code == 200
    assert resp.json()["device_id"] == "sensor-001"


@patch("app.main.get_db")
def test_device_latest_not_found(mock_get_db):
    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = None
    mock_conn = MagicMock()
    mock_conn.cursor.return_value.__enter__ = lambda s: mock_cursor
    mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    mock_get_db.return_value = mock_conn

    resp = client.get("/devices/nonexistent/latest")
    assert resp.status_code == 404


@patch("app.main.get_db")
def test_device_history(mock_get_db):
    mock_cursor = MagicMock()
    mock_cursor.fetchall.return_value = [
        {"id": "1", "device_id": "sensor-001", "data": {"pm2_5": 8.0}},
        {"id": "2", "device_id": "sensor-001", "data": {"pm2_5": 9.2}},
    ]
    mock_conn = MagicMock()
    mock_conn.cursor.return_value.__enter__ = lambda s: mock_cursor
    mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    mock_get_db.return_value = mock_conn

    resp = client.get("/devices/sensor-001/history?limit=2")
    assert resp.status_code == 200
    assert len(resp.json()) == 2


@patch("app.main.get_db")
def test_types_list(mock_get_db):
    mock_cursor = MagicMock()
    mock_cursor.fetchall.return_value = [
        {"slug": "air_quality", "name": "Air Quality Monitor"},
        {"slug": "soil", "name": "Soil Sensor"},
    ]
    mock_conn = MagicMock()
    mock_conn.cursor.return_value.__enter__ = lambda s: mock_cursor
    mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    mock_get_db.return_value = mock_conn

    resp = client.get("/types")
    assert resp.status_code == 200
    assert len(resp.json()) == 2


# ── Auth model — reads are public ────────────────────────

@patch("app.main.get_db")
def test_read_endpoints_need_no_auth(mock_get_db):
    mock_cursor = MagicMock()
    mock_cursor.fetchall.return_value = []
    mock_cursor.fetchone.return_value = None
    mock_conn = MagicMock()
    mock_conn.cursor.return_value.__enter__ = lambda s: mock_cursor
    mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    mock_get_db.return_value = mock_conn

    assert client.get("/devices").status_code == 200
    assert client.get("/devices/x/history").status_code == 200
    assert client.get("/types").status_code == 200
    assert client.get("/devices/x/latest").status_code == 404
