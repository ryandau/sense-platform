"""
sense.donohue.ai - Generic IoT Ingest API
Accepts readings from any device type.
Deployed as AWS Lambda via Mangum.
"""

from datetime import datetime, timezone
from typing import Optional, Any
import json
import os

import boto3
from fastapi import FastAPI, HTTPException, Security
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security.api_key import APIKeyHeader
from mangum import Mangum
from pydantic import BaseModel, Field, field_validator
import psycopg2
from psycopg2.extras import RealDictCursor, Json

app = FastAPI(title="Sense Platform Ingest API", version="1.0.0")

_frontend_domain = os.environ.get("FRONTEND_DOMAIN", "localhost")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[f"https://{_frontend_domain}", f"http://{_frontend_domain}"],
    allow_methods=["*"],
    allow_headers=["Content-Type", "X-API-Key"],
)

API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=True)

# Cache secrets across Lambda invocations (same container)
_sm = boto3.client("secretsmanager")
_db_secret = None
_api_key = None


def _get_db_secret():
    global _db_secret
    if _db_secret is None:
        resp = _sm.get_secret_value(SecretId=os.environ["DB_SECRET_ARN"])
        _db_secret = json.loads(resp["SecretString"])
    return _db_secret


def _get_api_key():
    global _api_key
    if _api_key is None:
        resp = _sm.get_secret_value(SecretId=os.environ["API_KEY_SECRET_ARN"])
        _api_key = resp["SecretString"]
    return _api_key


def verify_api_key(api_key: str = Security(API_KEY_HEADER)):
    if api_key != _get_api_key():
        raise HTTPException(status_code=403, detail="Invalid API key")
    return api_key


def get_db():
    secret = _get_db_secret()
    return psycopg2.connect(
        host=secret["host"],
        port=secret.get("port", 5432),
        dbname=secret.get("dbname", "sense"),
        user=secret["username"],
        password=secret["password"],
        cursor_factory=RealDictCursor
    )


class ReadingPayload(BaseModel):
    device_id:      str = Field(..., description="Unique device identifier")
    type_slug:      Optional[str] = Field(None)
    recorded_at:    datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    latitude:       Optional[float] = Field(None, ge=-90, le=90)
    longitude:      Optional[float] = Field(None, ge=-180, le=180)
    location_label: Optional[str] = None
    country_code:   Optional[str] = Field(None, min_length=2, max_length=2)
    data:           dict[str, Any] = Field(..., description="Sensor readings")
    computed:       Optional[dict[str, Any]] = None

    @field_validator("country_code")
    @classmethod
    def uppercase_country(cls, v):
        return v.upper() if v else v

    @field_validator("data")
    @classmethod
    def data_not_empty(cls, v):
        if not v:
            raise ValueError("data field cannot be empty")
        return v


def compute_air_quality(data: dict) -> dict:
    computed = {}
    pm25 = data.get("pm2_5")
    if pm25 is not None:
        if pm25 <= 12.0:
            aqi = round((50.0 / 12.0) * pm25)
        elif pm25 <= 35.4:
            aqi = round(((100 - 51) / (35.4 - 12.1)) * (pm25 - 12.1) + 51)
        elif pm25 <= 55.4:
            aqi = round(((150 - 101) / (55.4 - 35.5)) * (pm25 - 35.5) + 101)
        elif pm25 <= 150.4:
            aqi = round(((200 - 151) / (150.4 - 55.5)) * (pm25 - 55.5) + 151)
        elif pm25 <= 250.4:
            aqi = round(((300 - 201) / (250.4 - 150.5)) * (pm25 - 150.5) + 201)
        else:
            aqi = round(((500 - 301) / (500.4 - 250.5)) * (pm25 - 250.5) + 301)

        computed["aqi"] = aqi
        computed["aqi_category"] = (
            "Good" if aqi <= 50 else
            "Moderate" if aqi <= 100 else
            "Unhealthy for Sensitive Groups" if aqi <= 150 else
            "Unhealthy" if aqi <= 200 else
            "Very Unhealthy" if aqi <= 300 else
            "Hazardous"
        )

    co2 = data.get("co2_ppm")
    if co2 is not None:
        computed["co2_status"] = (
            "Good" if co2 < 800 else
            "Acceptable" if co2 < 1000 else
            "Poor" if co2 < 1500 else
            "Very Poor" if co2 < 2000 else
            "Dangerous"
        )
    return computed


def enrich(payload: ReadingPayload) -> dict:
    computed = payload.computed or {}
    if payload.type_slug == "air_quality":
        computed.update(compute_air_quality(payload.data))
    return computed if computed else None


def build_summary(payload: ReadingPayload, computed: dict) -> str:
    parts = [
        f"Device {payload.device_id} ({payload.type_slug or 'unknown type'})",
        f"recorded at {payload.recorded_at.isoformat()}",
    ]
    if payload.location_label:
        parts.append(f"in {payload.location_label}")
    if payload.country_code:
        parts.append(f"({payload.country_code})")
    parts.append("reported:")
    for key, value in payload.data.items():
        parts.append(f"{key}={value}")
    if computed:
        parts.append("computed:")
        for key, value in computed.items():
            parts.append(f"{key}={value}")
    return " ".join(parts)


@app.post("/ingest", status_code=201)
def ingest_reading(payload: ReadingPayload, api_key: str = Security(verify_api_key)):
    computed = enrich(payload)
    try:
        conn = get_db()
        with conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO devices (device_id, type_slug, last_seen_at)
                    VALUES (%s, %s, NOW())
                    ON CONFLICT (device_id) DO UPDATE
                    SET last_seen_at = NOW(),
                        type_slug = COALESCE(EXCLUDED.type_slug, devices.type_slug)
                """, (payload.device_id, payload.type_slug))

                cur.execute("""
                    INSERT INTO readings (
                        device_id, type_slug, recorded_at,
                        latitude, longitude, location_label, country_code,
                        data, computed
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                """, (
                    payload.device_id, payload.type_slug, payload.recorded_at,
                    payload.latitude, payload.longitude,
                    payload.location_label, payload.country_code,
                    Json(payload.data),
                    Json(computed) if computed else None,
                ))
                reading_id = cur.fetchone()["id"]
        conn.close()
        response = {"status": "accepted", "reading_id": str(reading_id)}
        if computed:
            response["computed"] = computed
        return response
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/health")
def health():
    return {"status": "ok", "service": "sense-ingest"}


@app.get("/devices")
def list_devices():
    try:
        conn = get_db()
        with conn.cursor() as cur:
            cur.execute("""
                SELECT d.*, COUNT(r.id) as reading_count,
                       MAX(r.recorded_at) as last_reading_at
                FROM devices d
                LEFT JOIN readings r ON r.device_id = d.device_id
                GROUP BY d.id ORDER BY d.last_seen_at DESC
            """)
            rows = cur.fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/devices/{device_id}/latest")
def latest_reading(device_id: str):
    try:
        conn = get_db()
        with conn.cursor() as cur:
            cur.execute("""
                SELECT * FROM readings WHERE device_id = %s
                ORDER BY recorded_at DESC LIMIT 1
            """, (device_id,))
            row = cur.fetchone()
        conn.close()
        if not row:
            raise HTTPException(status_code=404, detail="No readings found")
        return dict(row)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/devices/{device_id}/history")
def reading_history(device_id: str, limit: int = 100):
    try:
        conn = get_db()
        with conn.cursor() as cur:
            cur.execute("""
                SELECT * FROM readings WHERE device_id = %s
                ORDER BY recorded_at DESC LIMIT %s
            """, (device_id, min(limit, 1000)))
            rows = cur.fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/types")
def list_device_types():
    try:
        conn = get_db()
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM device_types ORDER BY name")
            rows = cur.fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


handler = Mangum(app, lifespan="off")