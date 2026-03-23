"""
Tests for sense-platform API endpoints.
Uses FastAPI TestClient with mocked database and secrets.
"""
import sys
import os
import json
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

# Set env vars before importing the app (it reads them at module level)
os.environ.setdefault("DB_SECRET_ARN", "arn:aws:secretsmanager:ap-southeast-2:000000000000:secret:test")
os.environ.setdefault("API_KEY_SECRET_ARN", "arn:aws:secretsmanager:ap-southeast-2:000000000000:secret:test-key")
os.environ.setdefault("FRONTEND_DOMAIN", "localhost")

# Mock boto3 before importing the app (it initialises a client at module level)
mock_sm = MagicMock()
with patch("boto3.client", return_value=mock_sm):
    from fastapi.testclient import TestClient
    from backend.app.api.ingest import app

client = TestClient(app)

TEST_API_KEY = "test-api-key-12345"


def setup_mocks():
    """Configure mock responses for secrets and database."""
    mock_sm.get_secret_value.side_effect = lambda SecretId: {
        "SecretString": json.dumps({
            "host": "localhost", "port": 5432,
            "dbname": "sense", "username": "test", "password": "test"
        }) if "secret:test" in SecretId and "key" not in SecretId
        else {"SecretString": TEST_API_KEY}
    }[list({"SecretString": json.dumps({
        "host": "localhost", "port": 5432,
        "dbname": "sense", "username": "test", "password": "test"
    }) if "key" not in SecretId else TEST_API_KEY}.keys())[0]]

    # Reset cached secrets
    import backend.app.api.ingest as mod
    mod._api_key = None
    mod._db_secret = None


def mock_secret_value(SecretId):
    if "key" in SecretId:
        return {"SecretString": TEST_API_KEY}
    return {"SecretString": json.dumps({
        "host": "localhost", "port": 5432,
        "dbname": "sense", "username": "test", "password": "test",
    })}


# ─────────────────────────────────────────
# Health endpoint (no auth, no DB)
# ─────────────────────────────────────────

def test_health():
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


# ─────────────────────────────────────────
# Ingest endpoint (requires auth + DB)
# ─────────────────────────────────────────

def test_ingest_missing_api_key():
    resp = client.post("/ingest", json={
        "device_id": "test-001",
        "data": {"pm2_5": 8.0},
    })
    assert resp.status_code == 403


def test_ingest_invalid_api_key():
    import backend.app.api.ingest as mod
    mod._api_key = None
    mock_sm.get_secret_value.side_effect = mock_secret_value

    resp = client.post("/ingest",
        json={"device_id": "test-001", "data": {"pm2_5": 8.0}},
        headers={"X-API-Key": "wrong-key"},
    )
    assert resp.status_code == 403


@patch("backend.app.api.ingest.get_db")
def test_ingest_success(mock_get_db):
    import backend.app.api.ingest as mod
    mod._api_key = None
    mock_sm.get_secret_value.side_effect = mock_secret_value

    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = {"id": "abc-123"}
    mock_conn.cursor.return_value.__enter__ = lambda s: mock_cursor
    mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    mock_conn.__enter__ = lambda s: mock_conn
    mock_conn.__exit__ = MagicMock(return_value=False)
    mock_get_db.return_value = mock_conn

    resp = client.post("/ingest",
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


@patch("backend.app.api.ingest.get_db")
def test_ingest_empty_data_rejected(mock_get_db):
    import backend.app.api.ingest as mod
    mod._api_key = None
    mock_sm.get_secret_value.side_effect = mock_secret_value

    resp = client.post("/ingest",
        json={"device_id": "test-001", "data": {}},
        headers={"X-API-Key": TEST_API_KEY},
    )
    assert resp.status_code == 422


# ─────────────────────────────────────────
# Read endpoints (public, no auth)
# ─────────────────────────────────────────

@patch("backend.app.api.ingest.get_db")
def test_devices_list(mock_get_db):
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.fetchall.return_value = [
        {"id": "1", "device_id": "sensor-001", "type_slug": "air_quality",
         "reading_count": 5, "last_reading_at": None},
    ]
    mock_conn.cursor.return_value.__enter__ = lambda s: mock_cursor
    mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    mock_get_db.return_value = mock_conn

    resp = client.get("/devices")
    assert resp.status_code == 200
    assert len(resp.json()) == 1
    assert resp.json()[0]["device_id"] == "sensor-001"


@patch("backend.app.api.ingest.get_db")
def test_device_latest(mock_get_db):
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = {
        "id": "abc", "device_id": "sensor-001",
        "data": {"pm2_5": 8.0}, "computed": {"aqi": 33},
    }
    mock_conn.cursor.return_value.__enter__ = lambda s: mock_cursor
    mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    mock_get_db.return_value = mock_conn

    resp = client.get("/devices/sensor-001/latest")
    assert resp.status_code == 200
    assert resp.json()["device_id"] == "sensor-001"


@patch("backend.app.api.ingest.get_db")
def test_device_latest_not_found(mock_get_db):
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = None
    mock_conn.cursor.return_value.__enter__ = lambda s: mock_cursor
    mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    mock_get_db.return_value = mock_conn

    resp = client.get("/devices/nonexistent/latest")
    assert resp.status_code == 404


@patch("backend.app.api.ingest.get_db")
def test_device_history(mock_get_db):
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.fetchall.return_value = [
        {"id": "1", "device_id": "sensor-001", "data": {"pm2_5": 8.0}},
        {"id": "2", "device_id": "sensor-001", "data": {"pm2_5": 9.2}},
    ]
    mock_conn.cursor.return_value.__enter__ = lambda s: mock_cursor
    mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    mock_get_db.return_value = mock_conn

    resp = client.get("/devices/sensor-001/history?limit=2")
    assert resp.status_code == 200
    assert len(resp.json()) == 2


@patch("backend.app.api.ingest.get_db")
def test_types_list(mock_get_db):
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.fetchall.return_value = [
        {"slug": "air_quality", "name": "Air Quality Monitor"},
        {"slug": "soil", "name": "Soil Sensor"},
    ]
    mock_conn.cursor.return_value.__enter__ = lambda s: mock_cursor
    mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    mock_get_db.return_value = mock_conn

    resp = client.get("/types")
    assert resp.status_code == 200
    assert len(resp.json()) == 2


# ─────────────────────────────────────────
# Auth model — verify reads are public
# ─────────────────────────────────────────

@patch("backend.app.api.ingest.get_db")
def test_read_endpoints_need_no_auth(mock_get_db):
    """All GET endpoints should work without an API key."""
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.fetchall.return_value = []
    mock_cursor.fetchone.return_value = None
    mock_conn.cursor.return_value.__enter__ = lambda s: mock_cursor
    mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    mock_get_db.return_value = mock_conn

    # These should all succeed without X-API-Key header
    assert client.get("/devices").status_code == 200
    assert client.get("/devices/x/history").status_code == 200
    assert client.get("/types").status_code == 200
    # latest returns 404 (no data) but NOT 403
    assert client.get("/devices/x/latest").status_code == 404
