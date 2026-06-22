"""
Tests for sense-platform ingest API — unit tests for engine, models, and content string.
"""

from datetime import datetime, timezone
from app.main import (
    BreakpointEngine,
    build_content_string,
    ReadingPayload,
)
import app.main as mod
from tests._breakpoints import seed_breakpoints


engine = BreakpointEngine()


def _compute(data):
    seed_breakpoints(mod)
    return engine.compute("air_quality", data, None)


# ── Breakpoint Engine ──

def test_aqi_good():
    result = _compute({"pm2_5": 6.0})
    assert result["aqi"] <= 50
    assert result["aqi_category"] == "Good"


def test_aqi_unhealthy_sensitive():
    result = _compute({"pm2_5": 47.0})
    assert result["aqi_category"] == "Unhealthy for Sensitive Groups"


def test_aqi_hazardous():
    result = _compute({"pm2_5": 300.0})
    assert result["aqi_category"] == "Hazardous"


def test_aqi_au_category():
    result = _compute({"pm2_5": 8.0})
    assert result["aqi_au_category"] == "Good"
    result = _compute({"pm2_5": 30.0})
    assert result["aqi_au_category"] == "Fair"


def test_co2_good():
    result = _compute({"co2_ppm": 500})
    assert result["co2_status"] == "Good"


def test_co2_dangerous():
    result = _compute({"co2_ppm": 2500})
    assert result["co2_status"] == "Dangerous"


def test_empty_data_no_crash():
    result = _compute({})
    assert result == {}


# ── Payload Validation ──

def test_payload_country_uppercase():
    payload = ReadingPayload(
        device_id="test-001",
        country_code="au",
        data={"pm2_5": 10.0}
    )
    assert payload.country_code == "AU"


def test_payload_recorded_at_defaults():
    payload = ReadingPayload(
        device_id="test-001",
        data={"pm2_5": 10.0}
    )
    assert payload.recorded_at is not None


# ── Content String Builder ──

FIELD_META = {
    "air_quality": {
        "pm2_5": {"label": "PM2.5", "unit": "μg/m³"},
        "co2_ppm": {"label": "CO2", "unit": "ppm"},
        "temperature_c": {"label": "Temperature", "unit": "°C"},
    }
}


def test_content_string_full():
    payload = ReadingPayload(
        device_id="sensor-001",
        type_slug="air_quality",
        recorded_at=datetime(2026, 3, 21, 4, 35, tzinfo=timezone.utc),
        location_label="Annerley, Brisbane",
        country_code="AU",
        latitude=-27.47,
        longitude=153.03,
        data={"pm2_5": 6.4, "co2_ppm": 520},
    )
    computed = {"aqi": 27, "aqi_category": "Good", "co2_status": "Good"}
    content = build_content_string(payload, computed, "Office Sensor", "Australia/Brisbane", FIELD_META)
    assert "WHO: Office Sensor" in content
    assert "Annerley, Brisbane" in content
    assert "PM2.5: 6.4 μg/m³" in content
    assert "CO2: 520 ppm" in content
    assert "Aqi: 27 (Good)" in content
    assert "2:35 PM AEST" in content


def test_content_string_minimal():
    payload = ReadingPayload(
        device_id="sensor-001",
        data={"pm2_5": 10.0},
    )
    content = build_content_string(payload, None, None, "Australia/Brisbane", None)
    assert "WHO: sensor-001" in content
    assert "WHAT:" in content
    assert "WHY:" not in content


def test_content_string_skips_nulls():
    payload = ReadingPayload(
        device_id="sensor-001",
        type_slug="air_quality",
        data={"pm2_5": 10.0, "co2_ppm": None},
    )
    content = build_content_string(payload, None, None, "Australia/Brisbane", FIELD_META)
    assert "PM2.5: 10.0" in content
    assert "CO2" not in content


def test_content_string_timezone_conversion():
    payload = ReadingPayload(
        device_id="sensor-001",
        recorded_at=datetime(2026, 3, 21, 0, 0, tzinfo=timezone.utc),
        data={"pm2_5": 5.0},
    )
    content = build_content_string(payload, None, None, "Australia/Brisbane", None)
    assert "10:00 AM AEST" in content


def test_content_string_invalid_timezone():
    payload = ReadingPayload(
        device_id="sensor-001",
        data={"pm2_5": 5.0},
    )
    content = build_content_string(payload, None, None, "Not/A/Timezone", None)
    assert "WHO: sensor-001" in content
    assert "UTC" in content
