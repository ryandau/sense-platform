"""
Shared breakpoint fixtures for the tests.

Seeds the breakpoint engine's in-memory cache so unit/API tests can compute
derived metrics without touching a database. Mirrors the seed data in
db/schema.sql (EPA PM2.5 AQI, AU NEPM category, CO2 status bands).
"""

BREAKPOINTS = {
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


def seed_breakpoints(mod):
    """Inject BREAKPOINTS into a loaded app module's engine cache."""
    mod._breakpoint_cache = BREAKPOINTS
    mod._breakpoint_cache_ts = float("inf")
