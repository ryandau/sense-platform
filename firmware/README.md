# Sense Platform Firmware for M5Stack AirQ Kit v1.1

Modified [AirQUserDemo](https://github.com/m5stack/AirQUserDemo) firmware
that sends sensor readings to your Sense Platform `/ingest` endpoint instead
of M5Stack's EzData cloud.

## Device Cycle

**On battery** (power off between readings):

1. RTC alarm fires → device boots (~8 seconds)
2. Connect WiFi, read SEN55 + SCD40 sensors
3. POST reading to `/ingest` with API key auth
4. Set next RTC alarm, cut power — device is fully off

**On USB** (delay loop):

1. Read sensors, POST to `/ingest`
2. Wait `sleep_interval` seconds
3. Repeat (no reboot)

The e-ink display shows a permanent QR code linking to the web dashboard.
Drawn once on first boot, persists unpowered through all cycles.

## Project Layout

```
firmware/airq/
  AirQUserDemo.ino     <- main sketch (~300 lines)
  SensePlatform.hpp/cpp <- HTTP client for /ingest
  DataBase.hpp/cpp      <- config persistence (db.json)
  Sensor.hpp/cpp        <- sensor drivers (SEN55, SCD40, BM8563)
  config.h              <- hardware pin defines
  platformio.ini        <- build config
  data/
    db.json.example     <- config template (copy to db.json)
```

## Quick Start

```bash
cd firmware/airq

# Copy config template and fill in your credentials
cp data/db.json.example data/db.json
# Edit data/db.json with WiFi, API, and dashboard URL

# Flash config to device filesystem
pio run --target uploadfs

# Build and flash firmware
pio run --target upload

# Monitor serial output (optional)
pio device monitor
```

## Configuration

Edit `data/db.json` before flashing. All settings are in the `sense` block:

```json
{
  "sense": {
    "endpoint": "https://YOUR_API_GATEWAY_URL/v1",
    "api_key": "YOUR_API_KEY",
    "device_id": "airq-001",
    "latitude": -27.4698,
    "longitude": 153.0251,
    "location_label": "Annerley",
    "country_code": "AU",
    "dashboard_url": "https://YOUR_DASHBOARD_URL"
  }
}
```

Other config: WiFi (`wifi.ssid`, `wifi.password`), reading interval
(`rtc.sleep_interval` in seconds), timezone (`ntp.tz`).

To change config, edit `db.json` and reflash with `pio run --target uploadfs`.

## Payload Format

Each cycle POSTs to `{endpoint}/ingest`:

```json
{
  "device_id": "airq-001",
  "type_slug": "air_quality",
  "latitude": -27.4698,
  "longitude": 153.0251,
  "location_label": "Annerley",
  "country_code": "AU",
  "data": {
    "pm1_0": 3.2,
    "pm2_5": 8.1,
    "pm4_0": 9.4,
    "pm10_0": 10.2,
    "temperature": 24.5,
    "humidity": 62.3,
    "voc_index": 105,
    "nox_index": 12,
    "co2_ppm": 687,
    "scd_temperature": 25.1,
    "scd_humidity": 58.7,
    "battery_mv": 4120
  }
}
```

Headers: `Content-Type: application/json`, `X-API-Key: <key>`

The platform auto-registers the device on first reading, computes AQI
breakpoints (EPA + Australian NEPM), and builds RAG content strings.
