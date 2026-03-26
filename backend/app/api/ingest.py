"""
sense.donohue.ai - Generic IoT Ingest API
Accepts readings from any device type.
Deployed as AWS Lambda via Mangum.
"""

from datetime import datetime, timezone
from typing import Optional, Any, Protocol
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
import json
import os
import time

import boto3
from fastapi import FastAPI, HTTPException, Security
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security.api_key import APIKeyHeader
from mangum import Mangum
from pydantic import BaseModel, Field, field_validator
import psycopg2
from psycopg2.extras import RealDictCursor, Json
from openai import OpenAI

app = FastAPI(title="Sense Platform Ingest API", version="1.0.0")

_frontend_domain = os.environ.get("FRONTEND_DOMAIN", "localhost")
_frontend_bucket_url = os.environ.get("FRONTEND_BUCKET_URL", "")
_cors_origins = [f"https://{_frontend_domain}", f"http://{_frontend_domain}"]
if _frontend_bucket_url:
    _cors_origins.append(_frontend_bucket_url)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
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


_openai_client = None

def _get_openai():
    global _openai_client
    if _openai_client is None:
        resp = _sm.get_secret_value(SecretId=os.environ["OPENAI_KEY_SECRET_ARN"])
        _openai_client = OpenAI(api_key=resp["SecretString"])
    return _openai_client


def generate_embedding(text: str) -> list[float]:
    client = _get_openai()
    resp = client.embeddings.create(model="text-embedding-3-small", input=text)
    return resp.data[0].embedding


def get_db():
    secret = _get_db_secret()
    return psycopg2.connect(
        host=secret["host"],
        port=secret.get("port", 5432),
        dbname=secret.get("dbname", "sense"),
        user=secret["username"],
        password=secret["password"],
        sslmode="require",
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


class ConversionEngine(Protocol):
    def compute(self, type_slug: str, data: dict, conn) -> dict: ...


_breakpoint_cache: dict | None = None
_breakpoint_cache_ts: float = 0
_CACHE_TTL = 300


class BreakpointEngine:
    def _load_breakpoints(self, conn) -> dict:
        global _breakpoint_cache, _breakpoint_cache_ts
        now = time.time()
        if _breakpoint_cache and (now - _breakpoint_cache_ts) < _CACHE_TTL:
            return _breakpoint_cache

        with conn.cursor() as cur:
            cur.execute("""
                SELECT type_slug, input_field, output_field,
                       bp_low, bp_high, idx_low, idx_high,
                       category, interpolate
                FROM breakpoints
                ORDER BY type_slug, input_field, sort_order
            """)
            rows = cur.fetchall()

        cache = {}
        for row in rows:
            key = (row["type_slug"], row["input_field"], row["output_field"])
            cache.setdefault(key, [])
            cache[key].append(row)

        _breakpoint_cache = cache
        _breakpoint_cache_ts = now
        return cache

    def compute(self, type_slug: str, data: dict, conn) -> dict:
        breakpoints = self._load_breakpoints(conn)
        computed = {}
        for field_name, value in data.items():
            if value is None:
                continue
            for cache_key, ranges in breakpoints.items():
                if cache_key[0] != type_slug or cache_key[1] != field_name:
                    continue
                output_field = cache_key[2]
                for bp in ranges:
                    if float(bp["bp_low"]) <= float(value) <= float(bp["bp_high"]):
                        if bp["interpolate"]:
                            idx = ((float(bp["idx_high"]) - float(bp["idx_low"]))
                                   / (float(bp["bp_high"]) - float(bp["bp_low"]))
                                   * (float(value) - float(bp["bp_low"]))
                                   + float(bp["idx_low"]))
                            computed[output_field] = round(idx)
                            computed[f"{output_field}_category"] = bp["category"]
                        else:
                            computed[output_field] = bp["category"]
                        break
        return computed


_engine: ConversionEngine = BreakpointEngine()


def enrich(payload: ReadingPayload, conn) -> dict:
    computed = payload.computed or {}
    if payload.type_slug:
        computed.update(_engine.compute(payload.type_slug, payload.data, conn))
    return computed if computed else None


_field_meta_cache: dict | None = None
_field_meta_cache_ts: float = 0


def _load_field_meta(conn) -> dict:
    global _field_meta_cache, _field_meta_cache_ts
    now = time.time()
    if _field_meta_cache and (now - _field_meta_cache_ts) < _CACHE_TTL:
        return _field_meta_cache

    with conn.cursor() as cur:
        cur.execute("SELECT slug, fields FROM device_types")
        rows = cur.fetchall()

    _field_meta_cache = {row["slug"]: row["fields"] for row in rows}
    _field_meta_cache_ts = now
    return _field_meta_cache


def _format_local_time(dt: datetime, tz_name: str) -> str:
    try:
        tz = ZoneInfo(tz_name)
    except (ZoneInfoNotFoundError, KeyError):
        tz = ZoneInfo("UTC")
    local = dt.astimezone(tz)
    return local.strftime("%A %-d %B %Y at %-I:%M %p %Z")


def build_content_string(
    payload: ReadingPayload,
    computed: dict | None,
    device_name: str | None,
    device_timezone: str,
    field_meta: dict | None,
) -> str:
    parts = []

    # WHO
    who = device_name or payload.device_id
    if payload.type_slug:
        who += f", {payload.type_slug.replace('_', ' ')} sensor"
    parts.append(f"WHO: {who}.")

    # WHERE
    where_parts = []
    if payload.location_label:
        where_parts.append(payload.location_label)
    if payload.country_code:
        where_parts.append(f"({payload.country_code})")
    if payload.latitude is not None and payload.longitude is not None:
        where_parts.append(f"Coordinates: {payload.latitude}, {payload.longitude}.")
    if where_parts:
        parts.append("WHERE: " + " ".join(where_parts))

    # WHEN
    time_str = _format_local_time(payload.recorded_at, device_timezone)
    parts.append(f"WHEN: {time_str}.")

    # WHAT — use field metadata for labels/units if available
    fields = (field_meta or {}).get(payload.type_slug, {}) if payload.type_slug else {}
    what = []
    for key, value in payload.data.items():
        if value is None:
            continue
        meta = fields.get(key, {})
        label = meta.get("label", key)
        unit = meta.get("unit", "")
        what.append(f"{label}: {value}{' ' + unit if unit else ''}")
    if what:
        parts.append("WHAT: " + ", ".join(what) + ".")

    # WHY — computed values
    if computed:
        why = []
        for key, value in computed.items():
            if key.endswith("_category"):
                continue
            label = key.replace("_", " ").title()
            if f"{key}_category" in computed:
                why.append(f"{label}: {value} ({computed[f'{key}_category']})")
            else:
                why.append(f"{label}: {value}")
        if why:
            parts.append("WHY: " + ", ".join(why) + ".")

    return "\n".join(parts)


@app.post("/ingest", status_code=201)
def ingest_reading(payload: ReadingPayload, api_key: str = Security(verify_api_key)):
    try:
        conn = get_db()
        computed = enrich(payload, conn)
        field_meta = _load_field_meta(conn)
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

                cur.execute(
                    "SELECT name, timezone FROM devices WHERE device_id = %s",
                    (payload.device_id,)
                )
                device_row = cur.fetchone()
                device_name = device_row["name"] if device_row else None
                device_tz = (device_row["timezone"] if device_row else None) or "Australia/Brisbane"

                content = build_content_string(payload, computed, device_name, device_tz, field_meta)

                try:
                    embedding = generate_embedding(content)
                except Exception as e:
                    print(f"Embedding generation failed: {e}")
                    embedding = None

                cur.execute("""
                    INSERT INTO reading_embeddings (reading_id, content, embedding, template_version)
                    VALUES (%s, %s, %s, 'v1')
                """, (reading_id, content, str(embedding) if embedding else None))

        conn.close()
        response = {"status": "accepted", "reading_id": str(reading_id)}
        if computed:
            response["computed"] = computed
        response["content"] = content
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


class AskContextPayload(BaseModel):
    question: str = Field(..., min_length=1, max_length=1000)
    device_id: Optional[str] = None
    hours: int = Field(default=24, ge=1, le=168)


@app.post("/ask-context")
def ask_context(payload: AskContextPayload):
    """Returns context from DB for the frontend to send to Claude Lambda."""
    try:
        conn = get_db()
        with conn.cursor() as cur:
            device_id = payload.device_id
            if not device_id:
                cur.execute("SELECT device_id FROM devices ORDER BY last_seen_at DESC LIMIT 1")
                row = cur.fetchone()
                if not row:
                    raise HTTPException(status_code=404, detail="No devices found")
                device_id = row["device_id"]

            cur.execute("""
                SELECT re.content, r.recorded_at
                FROM reading_embeddings re
                JOIN readings r ON r.id = re.reading_id
                WHERE r.device_id = %s
                  AND r.recorded_at > NOW() - INTERVAL '%s hours'
                ORDER BY r.recorded_at DESC
                LIMIT 50
            """, (device_id, payload.hours))
            readings = cur.fetchall()

            cur.execute("""
                SELECT title, content FROM knowledge_base
                WHERE type_slug IS NULL
                   OR type_slug = (SELECT type_slug FROM devices WHERE device_id = %s)
                ORDER BY category, title
            """, (device_id,))
            knowledge = cur.fetchall()

        conn.close()

        if not readings:
            raise HTTPException(status_code=404, detail="No recent readings found")

        context_parts = []
        context_parts.append("=== KNOWLEDGE BASE ===")
        for kb in knowledge:
            context_parts.append(f"## {kb['title']}\n{kb['content']}")
        context_parts.append(f"\n=== RECENT READINGS (last {payload.hours}h, newest first) ===")
        for r in readings:
            context_parts.append(r["content"])

        return {
            "context": "\n\n".join(context_parts),
            "device_id": device_id,
            "readings_used": len(readings),
            "knowledge_entries": len(knowledge),
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


handler = Mangum(app, lifespan="off")