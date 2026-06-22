"""
Tests for app.ai.retrieval helpers. Database access is mocked.
"""
import sys
import os
from unittest.mock import MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app.ai import retrieval


def _conn(fetchone_side_effect):
    cur = MagicMock()
    cur.fetchone.side_effect = fetchone_side_effect
    conn = MagicMock()
    conn.cursor.return_value.__enter__ = lambda s: cur
    conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    return conn, cur


def test_field_statistics():
    conn, cur = _conn([
        {"type_slug": "air_quality"},
        {"fields": {"pm2_5": {"label": "PM2.5", "unit": "μg/m³"},
                    "co2_ppm": {"label": "CO2", "unit": "ppm"}}},
        {"min_0": 0.0, "max_0": 689.4, "avg_0": 3.0,
         "min_1": 350.0, "max_1": 1200.0, "avg_1": 500.0},
    ])
    stats = retrieval.field_statistics(conn, "airq-001")
    assert stats["pm2_5"] == {"label": "PM2.5", "unit": "μg/m³", "min": 0.0, "max": 689.4, "avg": 3.0}
    assert stats["co2_ppm"]["max"] == 1200.0
    # field names are bound as parameters (injection-safe)
    sql, params = cur.execute.call_args[0]
    assert "FROM readings WHERE device_id = %s" in sql
    assert "pm2_5" in params and "co2_ppm" in params


def test_field_statistics_skips_fields_with_no_numeric_data():
    conn, _ = _conn([
        {"type_slug": "air_quality"},
        {"fields": {"pm2_5": {"label": "PM2.5", "unit": "μg/m³"}}},
        {"min_0": None, "max_0": None, "avg_0": None},  # no numeric values
    ])
    assert retrieval.field_statistics(conn, "airq-001") == {}


def test_field_statistics_no_device_type():
    conn, _ = _conn([{"type_slug": None}])
    assert retrieval.field_statistics(conn, "ghost") == {}


def test_recorded_categories():
    cur = MagicMock()
    cur.fetchall.return_value = [
        {"key": "aqi_category", "values": ["Moderate", "Good", "Hazardous"]},
        {"key": "co2_status", "values": ["Good", "Poor"]},
    ]
    conn = MagicMock()
    conn.cursor.return_value.__enter__ = lambda s: cur
    conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    out = retrieval.recorded_categories(conn, "airq-001")
    assert out["aqi_category"] == ["Good", "Hazardous", "Moderate"]  # sorted
    assert out["co2_status"] == ["Good", "Poor"]
