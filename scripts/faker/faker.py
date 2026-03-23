"""
sense.donohue.ai — Sensor Faker
Simulates realistic sensor data matching M5Stack Air Quality Kit v1.1
(SEN55 + SCD40) output fields. Uses real baseline values with natural
drift patterns for time-of-day, occupancy, and weather variation.

Usage:
    python faker.py --dry-run
    python faker.py --once
    python faker.py --loop
    python faker.py --loop --interval 30
    python faker.py --type soil --dry-run
    python faker.py --all --dry-run
    python faker.py --list

Environment:
    INGEST_URL  — API endpoint (default: http://localhost:8000/ingest)
    API_KEY     — API key for ingest endpoint
"""

import argparse
import json
import math
import os
import random
import time
from datetime import datetime, timezone

import httpx

INGEST_URL = os.environ.get("INGEST_URL", "http://localhost:8000/ingest")
API_KEY = os.environ.get("API_KEY", "dev-key-change-me")


# ─────────────────────────────────────────
# Realistic baselines (from real sensor readings)
# ─────────────────────────────────────────

# Indoor room with air filter running — Brisbane, subtropical climate
INDOOR_BASELINE = {
    "pm1_0": 3.0,
    "pm2_5": 8.0,
    "pm4_0": 12.0,
    "pm10_0": 17.0,
    "temperature_c": 27.0,
    "humidity_pct": 71.0,
    "co2_ppm": 402,
    "voc_index": 85,
    "nox_index": 12,
}


def hour_factor():
    """Returns 0-1 based on time of day. Peaks mid-afternoon, lowest at 4am."""
    hour = datetime.now().hour + datetime.now().minute / 60
    return 0.5 + 0.5 * math.sin((hour - 4) * math.pi / 12)


def occupancy_factor():
    """Simulates room occupancy — higher during waking hours."""
    hour = datetime.now().hour
    if 8 <= hour <= 23:
        return 0.7 + random.uniform(0, 0.3)
    return 0.1 + random.uniform(0, 0.2)


def drift(base, pct=0.08):
    """Add small random drift to a value."""
    return base + base * random.uniform(-pct, pct)


# ─────────────────────────────────────────
# Data generators
# ─────────────────────────────────────────

def generate_air_quality(config: dict, **kwargs) -> dict:
    b = INDOOR_BASELINE
    hf = hour_factor()
    occ = occupancy_factor()

    # PM scales slightly with time of day and window state
    pm_mult = 0.8 + hf * 0.4 + random.uniform(-0.1, 0.1)
    pm2_5 = max(1.0, drift(b["pm2_5"]) * pm_mult)

    # Maintain realistic PM ratios (PM1 < PM2.5 < PM4 < PM10)
    pm1_0 = round(pm2_5 * random.uniform(0.30, 0.45), 1)
    pm2_5 = round(pm2_5, 1)
    pm4_0 = round(pm2_5 * random.uniform(1.3, 1.6), 1)
    pm10_0 = round(pm2_5 * random.uniform(1.8, 2.4), 1)

    # CO2 rises with occupancy, baseline ~400 outdoor
    co2 = 400 + occ * random.uniform(80, 250) + drift(0, 1) * 20
    co2 = round(max(380, co2))

    # Temperature: SEN55 reads ~3C high from self-heating
    # Real room temp ~27C, sensor shows ~30C
    sensor_temp = b["temperature_c"] + 3.0
    temp = round(drift(sensor_temp, 0.03) + hf * 0.8 - 0.4, 1)

    # Humidity: subtropical Brisbane, inversely correlated with temp
    humidity = round(drift(b["humidity_pct"], 0.05) - hf * 3, 1)
    humidity = max(35, min(85, humidity))

    # VOC index: 0-500, higher with occupancy and cooking
    voc = b["voc_index"] + occ * random.uniform(10, 60)
    voc = round(max(1, drift(voc, 0.15)))

    # NOx index: generally low indoors
    nox = b["nox_index"] + occ * random.uniform(0, 15)
    nox = round(max(1, drift(nox, 0.2)))

    return {
        "pm1_0": pm1_0,
        "pm2_5": pm2_5,
        "pm4_0": pm4_0,
        "pm10_0": pm10_0,
        "temperature_c": temp,
        "humidity_pct": humidity,
        "co2_ppm": co2,
        "voc_index": voc,
        "nox_index": nox,
    }


def generate_soil(config: dict, **kwargs) -> dict:
    hf = hour_factor()
    return {
        "moisture_pct": round(drift(48) - hf * 5, 1),
        "temperature_c": round(drift(22) + hf * 3, 1),
        "ph": round(drift(6.4, 0.03), 2),
        "nitrogen_ppm": round(drift(28), 1),
        "phosphorus_ppm": round(drift(22), 1),
        "potassium_ppm": round(drift(120), 1),
    }


def generate_water_quality(config: dict, **kwargs) -> dict:
    return {
        "ph": round(drift(7.1, 0.03), 2),
        "turbidity_ntu": round(drift(1.2, 0.15), 2),
        "dissolved_o2": round(drift(8.0, 0.05), 2),
        "temperature_c": round(drift(23, 0.04), 1),
        "conductivity": round(drift(240, 0.08), 1),
        "tds_ppm": round(drift(160, 0.08), 1),
    }


def generate_noise(config: dict, **kwargs) -> dict:
    hour = datetime.now().hour
    base = 52 if 7 <= hour <= 22 else 34
    return {
        "db_avg": round(base + random.uniform(-4, 8), 1),
        "db_peak": round(base + random.uniform(8, 22), 1),
        "db_min": round(base - random.uniform(5, 12), 1),
    }


GENERATORS = {
    "air_quality": generate_air_quality,
    "soil": generate_soil,
    "water_quality": generate_water_quality,
    "noise": generate_noise,
}


# ─────────────────────────────────────────
# Device definitions
# ─────────────────────────────────────────
DEVICES = {
    "air_quality_brisbane": {
        "device_id": "faker-aq-brisbane",
        "type_slug": "air_quality",
        "location_label": "Annerley, Brisbane",
        "country_code": "AU",
        "latitude": -27.5018,
        "longitude": 153.0180,
    },
    "soil_garden": {
        "device_id": "faker-soil-garden",
        "type_slug": "soil",
        "location_label": "Annerley Back Garden",
        "country_code": "AU",
        "latitude": -27.5018,
        "longitude": 153.0180,
    },
    "water_tank": {
        "device_id": "faker-water-tank",
        "type_slug": "water_quality",
        "location_label": "Rainwater Tank",
        "country_code": "AU",
        "latitude": -27.5018,
        "longitude": 153.0180,
    },
    "noise_street": {
        "device_id": "faker-noise-street",
        "type_slug": "noise",
        "location_label": "Annerley Street",
        "country_code": "AU",
        "latitude": -27.5018,
        "longitude": 153.0180,
    },
}


# ─────────────────────────────────────────
# Send to ingest
# ─────────────────────────────────────────
def send_reading(payload: dict, dry_run: bool = False) -> bool:
    if dry_run:
        print(json.dumps(payload, indent=2, default=str))
        return True

    try:
        resp = httpx.post(
            INGEST_URL,
            json=payload,
            headers={"X-API-Key": API_KEY},
            timeout=10,
        )
        resp.raise_for_status()
        result = resp.json()
        computed = result.get("computed", {})
        computed_str = " | ".join(f"{k}={v}" for k, v in computed.items()) if computed else ""
        print(f"  ✓ reading_id={result['reading_id']}"
              + (f" | {computed_str}" if computed_str else ""))
        return True
    except Exception as e:
        print(f"  ✗ Failed: {e}")
        return False


# ─────────────────────────────────────────
# Run device
# ─────────────────────────────────────────
def run_device(key: str, config: dict, dry_run: bool = False):
    print(f"\n→ {config['device_id']} [{config['type_slug']}] "
          f"@ {config['location_label']}")

    generator = GENERATORS.get(config["type_slug"])
    if not generator:
        print(f"  No generator for type: {config['type_slug']}")
        return

    data = generator(config)

    payload = {
        "device_id": config["device_id"],
        "type_slug": config["type_slug"],
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "latitude": config.get("latitude"),
        "longitude": config.get("longitude"),
        "location_label": config.get("location_label"),
        "country_code": config.get("country_code"),
        "data": data,
    }

    payload = {k: v for k, v in payload.items() if v is not None}
    send_reading(payload, dry_run=dry_run)


# ─────────────────────────────────────────
# Main
# ─────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Sense Platform Faker")
    parser.add_argument("--device", choices=list(DEVICES.keys()),
                        help="Run a specific device")
    parser.add_argument("--type", choices=list(GENERATORS.keys()),
                        help="Run all devices of a type")
    parser.add_argument("--all", action="store_true",
                        help="Run all devices")
    parser.add_argument("--list", action="store_true",
                        help="List available devices")
    parser.add_argument("--once", action="store_true",
                        help="Send one reading (default air quality)")
    parser.add_argument("--loop", action="store_true",
                        help="Send readings continuously")
    parser.add_argument("--interval", type=int, default=60,
                        help="Seconds between readings in loop mode (default: 60)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print payload without sending")
    args = parser.parse_args()

    if args.list:
        print("\nAvailable devices:")
        for key, config in DEVICES.items():
            print(f"  {key:<30} [{config['type_slug']}] {config['location_label']}")
        return

    # Determine targets
    if args.all:
        targets = list(DEVICES.items())
    elif args.type:
        targets = [(k, v) for k, v in DEVICES.items()
                    if v["type_slug"] == args.type]
    elif args.device:
        targets = [(args.device, DEVICES[args.device])]
    elif args.once or args.loop:
        targets = [("air_quality_brisbane", DEVICES["air_quality_brisbane"])]
    else:
        parser.print_help()
        return

    if args.loop:
        print(f"Looping every {args.interval}s (Ctrl+C to stop)")
        try:
            while True:
                for key, config in targets:
                    run_device(key, config, dry_run=args.dry_run)
                time.sleep(args.interval)
        except KeyboardInterrupt:
            print("\nStopped.")
    else:
        for key, config in targets:
            run_device(key, config, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
