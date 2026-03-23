"""
Tests for sense-platform ingest API — unit tests for engine, models, and content string.
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from datetime import datetime, timezone
from backend.app.api.ingest import (
    BreakpointEngine,
    build_content_string,
    ReadingPayload,
)
import backend.app.api.ingest as mod


def _seed_cache():
    """Inject breakpoints into module cache so tests skip the DB."""
    mod._breakpoint_cache = {
        ("air_quality", "pm2_5", "aqi"): [
            {"bp_low": 0, "bp_high": 12.0, "idx_low": 0, "idx_high": 50, "category": "Good", "interpolate": True},
            {"bp_low": 12.1, "bp_high": 35.4, "idx_low": 51, "idx_high": 100, "category": "Moderate", "interpolate": True},
            {"bp_low": 35.5, "bp_high": 55.4, "idx_low": 101, "idx_high": 150, "category": "Unhealthy for Sensitive Groups", "interpolate": True},
            {"bp_low": 55.5, "bp_high": 150.4, "idx_low": 151, "idx_high": 200, "category": "Unhealthy", "interpolate": True},
            {"bp_low": 150.5, "bp_high": 250.4, "idx_low": 201, "idx_high": 300, "category": "Very Unhealthy", "interpolate": True},
            {"bp_low": 250.5, "bp_high": 500.4, "idx_low": 301, "idx_high": 500, "category": "Hazardous", "interpolate": True},
        ],
        ("air_quality", "pm2_5", "aqi_au_category"): [
            {"bp_low": 0, "bp_high": 24.9999, "idx_low": None, "idx_high": None, "category": "Good", "interpolate": False},
            {"bp_low": 25, "bp_high": 49.9999, "idx_low": None, "idx_high": None, "category": "Fair", "interpolate": False},
            {"bp_low": 50, "bp_high": 99.9999, "idx_low": None, "idx_high": None, "category": "Poor", "interpolate": False},
            {"bp_low": 100, "bp_high": 299.9999, "idx_low": None, "idx_high": None, "category": "Very Poor", "interpolate": False},
            {"bp_low": 300, "bp_high": 999.9999, "idx_low": None, "idx_high": None, "category": "Extremely Poor", "interpolate": False},
        ],
        ("air_quality", "co2_ppm", "co2_status"): [
            {"bp_low": 0, "bp_high": 799.9999, "idx_low": None, "idx_high": None, "category": "Good", "interpolate": False},
            {"bp_low": 800, "bp_high": 999.9999, "idx_low": None, "idx_high": None, "category": "Acceptable", "interpolate": False},
            {"bp_low": 1000, "bp_high": 1499.9999, "idx_low": None, "idx_high": None, "category": "Poor", "interpolate": False},
            {"bp_low": 1500, "bp_high": 1999.9999, "idx_low": None, "idx_high": None, "category": "Very Poor", "interpolate": False},
            {"bp_low": 2000, "bp_high": 99999, "idx_low": None, "idx_high": None, "category": "Dangerous", "interpolate": False},
        ],
    }
    mod._breakpoint_cache_ts = float("inf")


engine = BreakpointEngine()


def _compute(data):
    _seed_cache()
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
