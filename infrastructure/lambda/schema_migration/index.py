"""
CDK Trigger — Schema Migration
Runs once on first deploy to apply schema.sql to RDS.
Invoked by aws-cdk-lib/triggers.Trigger (not a raw CFN custom resource).
"""

import json
import os
import boto3
import psycopg2

SCHEMA_SQL = """
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

CREATE TABLE IF NOT EXISTS device_types (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    slug        VARCHAR(64) UNIQUE NOT NULL,
    name        VARCHAR(128) NOT NULL,
    description TEXT,
    fields      JSONB NOT NULL,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS devices (
    id           UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    device_id    VARCHAR(64) UNIQUE NOT NULL,
    type_slug    VARCHAR(64) REFERENCES device_types(slug),
    name         VARCHAR(128),
    firmware     VARCHAR(64),
    metadata     JSONB,
    created_at   TIMESTAMPTZ DEFAULT NOW(),
    last_seen_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS readings (
    id           UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    device_id    VARCHAR(64) NOT NULL REFERENCES devices(device_id),
    type_slug    VARCHAR(64) REFERENCES device_types(slug),
    recorded_at  TIMESTAMPTZ NOT NULL,
    received_at  TIMESTAMPTZ DEFAULT NOW(),
    latitude     DECIMAL(9,6),
    longitude    DECIMAL(9,6),
    location_label VARCHAR(128),
    country_code   CHAR(2),
    data         JSONB NOT NULL,
    computed     JSONB
);

CREATE INDEX IF NOT EXISTS idx_readings_device_time ON readings(device_id, recorded_at DESC);
CREATE INDEX IF NOT EXISTS idx_readings_time ON readings(recorded_at DESC);
CREATE INDEX IF NOT EXISTS idx_readings_type_time ON readings(type_slug, recorded_at DESC);
CREATE INDEX IF NOT EXISTS idx_readings_location ON readings(country_code, location_label);
CREATE INDEX IF NOT EXISTS idx_readings_data ON readings USING GIN(data);

CREATE TABLE IF NOT EXISTS reading_embeddings (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    reading_id  UUID NOT NULL REFERENCES readings(id) ON DELETE CASCADE,
    content     TEXT NOT NULL,
    embedding   vector(1536),
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS knowledge_base (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    type_slug   VARCHAR(64),
    category    VARCHAR(64) NOT NULL,
    title       VARCHAR(256) NOT NULL,
    content     TEXT NOT NULL,
    embedding   vector(1536),
    metadata    JSONB,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS alerts (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    reading_id  UUID REFERENCES readings(id),
    device_id   VARCHAR(64) REFERENCES devices(device_id),
    type_slug   VARCHAR(64),
    field       VARCHAR(64),
    value       DECIMAL(12,4),
    threshold   DECIMAL(12,4),
    severity    VARCHAR(16),
    message     TEXT,
    acknowledged_at TIMESTAMPTZ,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

INSERT INTO device_types (slug, name, description, fields) VALUES
('air_quality', 'Air Quality Monitor',
 'Monitors particulate matter, gases, CO2, temperature and humidity',
 '{"pm1_0":{"unit":"μg/m³","label":"PM1.0","range":[0,1000]},"pm2_5":{"unit":"μg/m³","label":"PM2.5","range":[0,1000]},"pm4_0":{"unit":"μg/m³","label":"PM4.0","range":[0,1000]},"pm10_0":{"unit":"μg/m³","label":"PM10","range":[0,1000]},"co2_ppm":{"unit":"ppm","label":"CO2","range":[0,40000]},"voc_index":{"unit":"idx","label":"VOC Index","range":[0,500]},"nox_index":{"unit":"idx","label":"NOx Index","range":[0,500]},"temperature_c":{"unit":"°C","label":"Temperature","range":[-40,85]},"humidity_pct":{"unit":"%RH","label":"Humidity","range":[0,100]}}'::jsonb)
ON CONFLICT (slug) DO NOTHING;

INSERT INTO device_types (slug, name, description, fields) VALUES
('soil', 'Soil Sensor', 'Monitors soil moisture, temperature, pH and nutrients',
 '{"moisture_pct":{"unit":"%","label":"Moisture","range":[0,100]},"temperature_c":{"unit":"°C","label":"Temperature","range":[-20,60]},"ph":{"unit":"pH","label":"pH","range":[0,14]},"nitrogen_ppm":{"unit":"ppm","label":"Nitrogen","range":[0,1000]},"phosphorus_ppm":{"unit":"ppm","label":"Phosphorus","range":[0,1000]},"potassium_ppm":{"unit":"ppm","label":"Potassium","range":[0,1000]}}'::jsonb)
ON CONFLICT (slug) DO NOTHING;

INSERT INTO device_types (slug, name, description, fields) VALUES
('water_quality', 'Water Quality Monitor', 'Monitors pH, turbidity, dissolved oxygen and temperature',
 '{"ph":{"unit":"pH","label":"pH","range":[0,14]},"turbidity_ntu":{"unit":"NTU","label":"Turbidity","range":[0,1000]},"dissolved_o2":{"unit":"mg/L","label":"Dissolved Oxygen","range":[0,20]},"temperature_c":{"unit":"°C","label":"Temperature","range":[-2,50]},"conductivity":{"unit":"μS/cm","label":"Conductivity","range":[0,10000]},"tds_ppm":{"unit":"ppm","label":"Total Dissolved Solids","range":[0,2000]}}'::jsonb)
ON CONFLICT (slug) DO NOTHING;

INSERT INTO device_types (slug, name, description, fields) VALUES
('noise', 'Noise Monitor', 'Monitors ambient sound levels',
 '{"db_avg":{"unit":"dB","label":"Average Level","range":[0,140]},"db_peak":{"unit":"dB","label":"Peak Level","range":[0,140]},"db_min":{"unit":"dB","label":"Minimum Level","range":[0,140]}}'::jsonb)
ON CONFLICT (slug) DO NOTHING;

INSERT INTO device_types (slug, name, description, fields) VALUES
('environment', 'Environment Monitor', 'General purpose environmental monitoring',
 '{"temperature_c":{"unit":"°C","label":"Temperature","range":[-40,85]},"humidity_pct":{"unit":"%RH","label":"Humidity","range":[0,100]},"pressure_hpa":{"unit":"hPa","label":"Pressure","range":[300,1100]},"dew_point_c":{"unit":"°C","label":"Dew Point","range":[-40,60]}}'::jsonb)
ON CONFLICT (slug) DO NOTHING;

INSERT INTO knowledge_base (type_slug, category, title, content) VALUES
('air_quality', 'thresholds', 'WHO PM2.5 Guidelines',
 'WHO Air Quality Guidelines (2021): PM2.5 annual mean should not exceed 5 μg/m³. 24-hour mean should not exceed 15 μg/m³. Levels above 35 μg/m³ are unhealthy for sensitive groups. Levels above 55 μg/m³ are unhealthy for all. Levels above 150 μg/m³ are very unhealthy. Levels above 250 μg/m³ are hazardous.')
ON CONFLICT DO NOTHING;

INSERT INTO knowledge_base (type_slug, category, title, content) VALUES
('air_quality', 'thresholds', 'CO2 Indoor Air Quality Guidelines',
 'CO2 guidelines: Below 800 ppm good. 800-1000 ppm acceptable. 1000-1500 ppm poor, ventilate. 1500-2000 ppm very poor, headaches likely. Above 2000 ppm dangerous, evacuate. Outdoor baseline ~420 ppm.')
ON CONFLICT DO NOTHING;

INSERT INTO knowledge_base (type_slug, category, title, content) VALUES
('air_quality', 'recommendations', 'Air Filter Selection Guide',
 'PM2.5 and particles: True HEPA filter. VOCs and gases: Activated carbon required. NO2 and SO2: Carbon with potassium permanganate. Combined pollution: HEPA plus activated carbon. Replace HEPA every 6-12 months. Replace carbon every 3-6 months in high VOC environments.')
ON CONFLICT DO NOTHING;
"""


def get_db_secret():
    sm = boto3.client("secretsmanager")
    resp = sm.get_secret_value(SecretId=os.environ["DB_SECRET_ARN"])
    return json.loads(resp["SecretString"])


def handler(event, context):
    """Invoked by CDK Trigger — just run the SQL and return.
    The Trigger framework handles CloudFormation signalling.
    All SQL uses IF NOT EXISTS / ON CONFLICT so this is safe to re-run."""
    print(f"Event: {json.dumps(event)}")

    secret = get_db_secret()
    conn = psycopg2.connect(
        host=secret["host"],
        port=secret.get("port", 5432),
        dbname=secret.get("dbname", "sense"),
        user=secret["username"],
        password=secret["password"],
    )
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute(SCHEMA_SQL)
    conn.close()
    print("Schema applied successfully")
    return {"status": "ok"}
