# Sense Platform Firmware for M5Stack AirQ Kit v1.1

Modified [AirQUserDemo](https://github.com/m5stack/AirQUserDemo) firmware
that sends sensor readings to your Sense Platform `/ingest` endpoint instead
of M5Stack's EzData cloud.

## Project Layout

```
firmware/
  airq/                  <- complete PlatformIO project, ready to build
    AirQUserDemo.ino     <- main sketch (EzData removed, SensePlatform wired in)
    SensePlatform.hpp/cpp <- HTTP client for Sense Platform /ingest
    DataBase.hpp/cpp      <- config persistence (sense.* fields added)
    AppWeb.cpp            <- web UI REST API (sense_config endpoint added)
    Sensor.hpp/cpp        <- unchanged sensor drivers
    MainAppView.hpp/cpp   <- unchanged e-ink UI
    config.h / misc.h     <- unchanged hardware defines
    platformio.ini        <- build config (ArduinoJson removed, not needed)
    data/                 <- LittleFS web UI assets
    airQConfig/           <- factory config templates
  SensePlatform.hpp/cpp   <- standalone module (for manual integration)
```

## Quick Start

```bash
cd firmware/airq
pio run --target upload
```

## Configuration

Connect to the device's WiFi AP, open `http://192.168.4.1`, and configure:
- WiFi credentials
- Sense Platform settings via POST to `/api/v1/sense_config`:

```json
{
  "sense": {
    "endpoint": "https://YOUR_API_GATEWAY_URL/v1",
    "api_key": "YOUR_API_KEY",
    "device_id": "airq-001",
    "latitude": -27.4698,
    "longitude": 153.0251,
    "location_label": "Brisbane CBD",
    "country_code": "AU"
  }
}
```

Or POST to `/api/v1/config` with the full config object including the `sense`
block — it's persisted to `/db.json` alongside WiFi, NTP, and buzzer settings.

## What Changed from Upstream

| Area | Original | Modified |
|------|----------|----------|
| Cloud client | `EzData.hpp/cpp` (ezdata2.m5stack.com) | `SensePlatform.hpp/cpp` (your API) |
| Config struct | `db.ezdata2.devToken` | `db.sense.{endpoint,apiKey,deviceId,lat,lng,...}` |
| Web API | `/api/v1/ezdata_config` | `/api/v1/sense_config` |
| Upload function | `uploadSensorRawData()` via EzData | `sensePlatform.upload()` direct POST |
| Run modes | 5 (incl. EzData QR screen) | 4 (EzData mode removed) |
| Dependencies | ArduinoJson | Removed (cJSON from ESP-IDF is sufficient) |

## Payload Format

Each upload POSTs to `{endpoint}/ingest`:

```json
{
  "device_id": "airq-001",
  "type_slug": "air_quality",
  "latitude": -27.4698,
  "longitude": 153.0251,
  "location_label": "Brisbane CBD",
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
    "co2": 687,
    "scd_temperature": 25.1,
    "scd_humidity": 58.7
  }
}
```

Headers: `Content-Type: application/json`, `X-API-Key: <key>`

The platform auto-registers the device on first reading, computes AQI
breakpoints (EPA + Australian NEPM), and builds RAG content strings.
