"""
Tests for sense-platform ingest API — unit tests for engine and models.
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from backend.app.api.ingest import (
    BreakpointEngine,
    build_summary,
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


def test_summary_builds():
    payload = ReadingPayload(
        device_id="faker-aq-brisbane",
        type_slug="air_quality",
        location_label="Annerley, Brisbane",
        country_code="AU",
        data={"pm2_5": 6.4, "co2_ppm": 520}
    )
    computed = _compute(payload.data)
    summary = build_summary(payload, computed)
    assert "faker-aq-brisbane" in summary
    assert "Annerley" in summary
    assert "pm2_5" in summary
