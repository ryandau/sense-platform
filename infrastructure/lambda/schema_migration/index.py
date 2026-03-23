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
    timezone     VARCHAR(64) DEFAULT 'Australia/Brisbane',
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
    id                UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    reading_id        UUID NOT NULL REFERENCES readings(id) ON DELETE CASCADE,
    content           TEXT NOT NULL,
    embedding         vector(1536),
    template_version  VARCHAR(16) DEFAULT 'v1',
    created_at        TIMESTAMPTZ DEFAULT NOW()
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

CREATE TABLE IF NOT EXISTS breakpoints (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    type_slug       VARCHAR(64) NOT NULL REFERENCES device_types(slug),
    input_field     VARCHAR(64) NOT NULL,
    output_field    VARCHAR(64) NOT NULL,
    bp_low          DECIMAL(12,4) NOT NULL,
    bp_high         DECIMAL(12,4) NOT NULL,
    idx_low         DECIMAL(12,4),
    idx_high        DECIMAL(12,4),
    category        VARCHAR(64),
    interpolate     BOOLEAN NOT NULL DEFAULT TRUE,
    sort_order      SMALLINT NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (type_slug, input_field, sort_order)
);

CREATE INDEX IF NOT EXISTS idx_breakpoints_lookup
    ON breakpoints(type_slug, input_field, sort_order);

-- EPA PM2.5 AQI breakpoints
INSERT INTO breakpoints (type_slug, input_field, output_field, bp_low, bp_high, idx_low, idx_high, category, interpolate, sort_order) VALUES
('air_quality', 'pm2_5', 'aqi', 0,     12.0,   0,   50,  'Good',                          TRUE, 1),
('air_quality', 'pm2_5', 'aqi', 12.1,  35.4,   51,  100, 'Moderate',                      TRUE, 2),
('air_quality', 'pm2_5', 'aqi', 35.5,  55.4,   101, 150, 'Unhealthy for Sensitive Groups', TRUE, 3),
('air_quality', 'pm2_5', 'aqi', 55.5,  150.4,  151, 200, 'Unhealthy',                     TRUE, 4),
('air_quality', 'pm2_5', 'aqi', 150.5, 250.4,  201, 300, 'Very Unhealthy',                TRUE, 5),
('air_quality', 'pm2_5', 'aqi', 250.5, 500.4,  301, 500, 'Hazardous',                     TRUE, 6)
ON CONFLICT DO NOTHING;

-- Australian NEPM PM2.5 categories (1-hour, QLD/NSW standard)
INSERT INTO breakpoints (type_slug, input_field, output_field, bp_low, bp_high, idx_low, idx_high, category, interpolate, sort_order) VALUES
('air_quality', 'pm2_5', 'aqi_au_category', 0,     24.9999, NULL, NULL, 'Good',            FALSE, 1),
('air_quality', 'pm2_5', 'aqi_au_category', 25,    49.9999, NULL, NULL, 'Fair',            FALSE, 2),
('air_quality', 'pm2_5', 'aqi_au_category', 50,    99.9999, NULL, NULL, 'Poor',            FALSE, 3),
('air_quality', 'pm2_5', 'aqi_au_category', 100,   299.9999, NULL, NULL, 'Very Poor',       FALSE, 4),
('air_quality', 'pm2_5', 'aqi_au_category', 300,   999.9999, NULL, NULL, 'Extremely Poor',  FALSE, 5)
ON CONFLICT DO NOTHING;

-- CO2 indoor air quality breakpoints
INSERT INTO breakpoints (type_slug, input_field, output_field, bp_low, bp_high, idx_low, idx_high, category, interpolate, sort_order) VALUES
('air_quality', 'co2_ppm', 'co2_status', 0,    799.9999,  NULL, NULL, 'Good',       FALSE, 1),
('air_quality', 'co2_ppm', 'co2_status', 800,  999.9999,  NULL, NULL, 'Acceptable', FALSE, 2),
('air_quality', 'co2_ppm', 'co2_status', 1000, 1499.9999, NULL, NULL, 'Poor',       FALSE, 3),
('air_quality', 'co2_ppm', 'co2_status', 1500, 1999.9999, NULL, NULL, 'Very Poor',  FALSE, 4),
('air_quality', 'co2_ppm', 'co2_status', 2000, 99999,     NULL, NULL, 'Dangerous',  FALSE, 5)
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
