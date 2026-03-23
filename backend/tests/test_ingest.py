"""
Tests for sense-platform ingest API.
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from backend.app.api.ingest import (
    compute_air_quality,
    build_summary,
    ReadingPayload,
)


def test_aqi_good():
    result = compute_air_quality({"pm2_5": 6.0})
    assert result["aqi"] <= 50
    assert result["aqi_category"] == "Good"


def test_aqi_unhealthy_sensitive():
    result = compute_air_quality({"pm2_5": 47.0})
    assert result["aqi_category"] == "Unhealthy for Sensitive Groups"


def test_aqi_hazardous():
    result = compute_air_quality({"pm2_5": 300.0})
    assert result["aqi_category"] == "Hazardous"


def test_co2_good():
    result = compute_air_quality({"co2_ppm": 500})
    assert result["co2_status"] == "Good"


def test_co2_dangerous():
    result = compute_air_quality({"co2_ppm": 2500})
    assert result["co2_status"] == "Dangerous"


def test_empty_data_no_crash():
    result = compute_air_quality({})
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
    computed = compute_air_quality(payload.data)
    summary = build_summary(payload, computed)
    assert "faker-aq-brisbane" in summary
    assert "Annerley" in summary
    assert "pm2_5" in summary