-- Generic IoT sensor platform schema
-- PostgreSQL 17 + pgvector

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ─────────────────────────────────────────
-- DEVICE TYPES
-- Defines what a category of device reports.
-- Acts as a schema registry for the AI layer.
-- ─────────────────────────────────────────
CREATE TABLE device_types (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    slug        VARCHAR(64) UNIQUE NOT NULL,  -- "air_quality", "soil", "water", "noise"
    name        VARCHAR(128) NOT NULL,         -- "Air Quality Monitor"
    description TEXT,
    fields      JSONB NOT NULL,               -- field definitions (see below)
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

-- fields JSONB structure:
-- {
--   "pm2_5":        { "unit": "μg/m³",  "label": "PM2.5",        "range": [0, 1000] },
--   "co2_ppm":      { "unit": "ppm",    "label": "CO2",           "range": [0, 40000] },
--   "temperature":  { "unit": "°C",     "label": "Temperature",   "range": [-40, 85] }
-- }

-- ─────────────────────────────────────────
-- DEVICES
-- One row per physical device.
-- ─────────────────────────────────────────
CREATE TABLE devices (
    id           UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    device_id    VARCHAR(64) UNIQUE NOT NULL,  -- "m5stack-001", "soil-garden-01"
    type_slug    VARCHAR(64) REFERENCES device_types(slug),
    name         VARCHAR(128),                  -- "Living Room", "Back Garden"
    firmware     VARCHAR(64),                   -- "esphome-1.0", "faker", "custom"
    metadata     JSONB,                         -- anything extra, hardware specs etc
    timezone     VARCHAR(64),                   -- IANA tz for local timestamps, e.g. "Australia/Brisbane"
    created_at   TIMESTAMPTZ DEFAULT NOW(),
    last_seen_at TIMESTAMPTZ
);

-- ─────────────────────────────────────────
-- READINGS
-- Completely generic — works for any device type.
-- ─────────────────────────────────────────
CREATE TABLE readings (
    id           UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    device_id    VARCHAR(64) NOT NULL REFERENCES devices(device_id),
    type_slug    VARCHAR(64) REFERENCES device_types(slug),
    recorded_at  TIMESTAMPTZ NOT NULL,
    received_at  TIMESTAMPTZ DEFAULT NOW(),

    -- Location at time of reading
    latitude     DECIMAL(9,6),
    longitude    DECIMAL(9,6),
    location_label VARCHAR(128),
    country_code   CHAR(2),

    -- All sensor data lives here — completely flexible
    data         JSONB NOT NULL,

    -- Optional computed/derived values (AQI, risk scores, alerts)
    computed     JSONB
);

-- Indexes for common query patterns
CREATE INDEX idx_readings_device_time
    ON readings(device_id, recorded_at DESC);

CREATE INDEX idx_readings_time
    ON readings(recorded_at DESC);

CREATE INDEX idx_readings_type_time
    ON readings(type_slug, recorded_at DESC);

CREATE INDEX idx_readings_location
    ON readings(country_code, location_label);

-- GIN index for querying inside JSONB data
CREATE INDEX idx_readings_data
    ON readings USING GIN(data);

-- ─────────────────────────────────────────
-- EMBEDDINGS
-- RAG layer — vectorised reading summaries
-- ─────────────────────────────────────────
CREATE TABLE reading_embeddings (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    reading_id  UUID NOT NULL REFERENCES readings(id) ON DELETE CASCADE,
    content     TEXT NOT NULL,       -- human-readable summary of reading
    embedding   vector(1536),        -- text-embedding-3-small dimensions
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_embeddings_vector
    ON reading_embeddings
    USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 100);

-- ─────────────────────────────────────────
-- KNOWLEDGE BASE
-- Documents for RAG: WHO guidelines, 
-- field interpretations, device manuals,
-- filter recommendations, safety thresholds
-- ─────────────────────────────────────────
CREATE TABLE knowledge_base (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    type_slug   VARCHAR(64),                  -- NULL = applies to all device types
    category    VARCHAR(64) NOT NULL,          -- "thresholds", "recommendations", "context"
    title       VARCHAR(256) NOT NULL,
    content     TEXT NOT NULL,
    embedding   vector(1536),
    metadata    JSONB,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_knowledge_vector
    ON knowledge_base
    USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 50);

CREATE INDEX idx_knowledge_type
    ON knowledge_base(type_slug, category);

-- ─────────────────────────────────────────
-- BREAKPOINTS
-- Database-driven derived metrics. The breakpoint engine reads these to
-- compute readings.computed (e.g. EPA AQI from PM2.5, CO2 status bands).
-- ─────────────────────────────────────────
CREATE TABLE breakpoints (
    id           UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    type_slug    VARCHAR(64) NOT NULL,
    input_field  VARCHAR(64) NOT NULL,
    output_field VARCHAR(64) NOT NULL,
    bp_low       DECIMAL(12,4) NOT NULL,
    bp_high      DECIMAL(12,4) NOT NULL,
    idx_low      DECIMAL(12,4),
    idx_high     DECIMAL(12,4),
    category     VARCHAR(64),
    interpolate  BOOLEAN NOT NULL DEFAULT TRUE,
    sort_order   SMALLINT NOT NULL DEFAULT 0,
    created_at   TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_breakpoints_lookup ON breakpoints(type_slug, input_field, sort_order);

-- US EPA PM2.5 AQI breakpoints (interpolated) + CO2 status bands (categorical)
INSERT INTO breakpoints (type_slug, input_field, output_field, bp_low, bp_high, idx_low, idx_high, category, interpolate, sort_order) VALUES
('air_quality', 'pm2_5', 'aqi',     0.0,   12.0,    0,   50, 'Good',                           TRUE, 1),
('air_quality', 'pm2_5', 'aqi',    12.1,   35.4,   51,  100, 'Moderate',                       TRUE, 2),
('air_quality', 'pm2_5', 'aqi',    35.5,   55.4,  101,  150, 'Unhealthy for Sensitive Groups', TRUE, 3),
('air_quality', 'pm2_5', 'aqi',    55.5,  150.4,  151,  200, 'Unhealthy',                      TRUE, 4),
('air_quality', 'pm2_5', 'aqi',   150.5,  250.4,  201,  300, 'Very Unhealthy',                 TRUE, 5),
('air_quality', 'pm2_5', 'aqi',   250.5,  500.4,  301,  500, 'Hazardous',                      TRUE, 6),
('air_quality', 'co2_ppm', 'co2_status',    0.0,  799.9999, NULL, NULL, 'Good',       FALSE, 1),
('air_quality', 'co2_ppm', 'co2_status',  800.0,  999.9999, NULL, NULL, 'Acceptable', FALSE, 2),
('air_quality', 'co2_ppm', 'co2_status', 1000.0, 1499.9999, NULL, NULL, 'Poor',       FALSE, 3),
('air_quality', 'co2_ppm', 'co2_status', 1500.0, 1999.9999, NULL, NULL, 'Very Poor',  FALSE, 4),
('air_quality', 'co2_ppm', 'co2_status', 2000.0, 99999.0,   NULL, NULL, 'Dangerous',  FALSE, 5);

-- ─────────────────────────────────────────
-- SEED DATA — Device Types
-- ─────────────────────────────────────────
INSERT INTO device_types (slug, name, description, fields) VALUES

('air_quality', 'Air Quality Monitor', 
 'Monitors particulate matter, gases, CO2, temperature and humidity',
 '{
   "pm1_0":         {"unit": "μg/m³", "label": "PM1.0",       "range": [0, 1000]},
   "pm2_5":         {"unit": "μg/m³", "label": "PM2.5",       "range": [0, 1000]},
   "pm4_0":         {"unit": "μg/m³", "label": "PM4.0",       "range": [0, 1000]},
   "pm10_0":        {"unit": "μg/m³", "label": "PM10",        "range": [0, 1000]},
   "co2_ppm":       {"unit": "ppm",   "label": "CO2",         "range": [0, 40000]},
   "voc_index":     {"unit": "idx",   "label": "VOC Index",   "range": [0, 500]},
   "nox_index":     {"unit": "idx",   "label": "NOx Index",   "range": [0, 500]},
   "temperature":   {"unit": "°C",    "label": "Temperature", "range": [-40, 85]},
   "humidity":      {"unit": "%RH",   "label": "Humidity",    "range": [0, 100]}
 }'::jsonb);

-- Additional sensor types are added the same way — the schema is type-agnostic;
-- readings.data is JSONB, so a new device_type only needs a row here.

-- ─────────────────────────────────────────
-- SEED DATA — Knowledge Base
-- WHO guidelines and thresholds
-- ─────────────────────────────────────────
INSERT INTO knowledge_base (type_slug, category, title, content) VALUES

('air_quality', 'thresholds', 'WHO PM2.5 Guidelines',
 'WHO Air Quality Guidelines (2021): PM2.5 annual mean should not exceed 5 μg/m³. 
  24-hour mean should not exceed 15 μg/m³. 
  Levels above 35 μg/m³ are considered unhealthy for sensitive groups.
  Levels above 55 μg/m³ are considered unhealthy for all.
  Levels above 150 μg/m³ are very unhealthy.
  Levels above 250 μg/m³ are hazardous.'),

('air_quality', 'thresholds', 'CO2 Indoor Air Quality Guidelines',
 'CO2 concentration guidelines for indoor air quality:
  Below 800 ppm: Good air quality, fresh air adequate.
  800-1000 ppm: Acceptable, consider ventilation.
  1000-1500 ppm: Poor, increase ventilation, may cause drowsiness.
  1500-2000 ppm: Very poor, headaches likely, ventilate immediately.
  Above 2000 ppm: Dangerous, evacuate and ventilate.
  Outdoor baseline is approximately 420 ppm.'),

('air_quality', 'recommendations', 'Air Filter Selection Guide',
 'Filter selection based on pollutant type:
  PM2.5 and particles: True HEPA filter (captures 99.97% of particles 0.3μm+).
  VOCs and gases: Activated carbon filter required in addition to HEPA.
  NO2 and SO2: Activated carbon with potassium permanganate impregnation.
  Combined pollution (PM + gases): Combination HEPA + activated carbon unit.
  For Almaty-type pollution (PM + coal gases): Combination filter essential.
  Replace HEPA filters every 6-12 months depending on pollution load.
  Replace carbon filters every 3-6 months in high VOC environments.');
