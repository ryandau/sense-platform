-- sense.donohue.ai
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
--   "temperature_c":{ "unit": "°C",     "label": "Temperature",   "range": [-40, 85] }
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
-- ALERTS
-- Threshold breaches, anomalies, events
-- ─────────────────────────────────────────
CREATE TABLE alerts (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    reading_id  UUID REFERENCES readings(id),
    device_id   VARCHAR(64) REFERENCES devices(device_id),
    type_slug   VARCHAR(64),
    field       VARCHAR(64),                  -- which field triggered the alert
    value       DECIMAL(12,4),               -- the value that triggered it
    threshold   DECIMAL(12,4),               -- the threshold that was breached
    severity    VARCHAR(16),                 -- "info", "warning", "critical"
    message     TEXT,
    acknowledged_at TIMESTAMPTZ,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_alerts_device ON alerts(device_id, created_at DESC);

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
   "temperature_c": {"unit": "°C",    "label": "Temperature", "range": [-40, 85]},
   "humidity_pct":  {"unit": "%RH",   "label": "Humidity",    "range": [0, 100]}
 }'::jsonb),

('soil', 'Soil Sensor',
 'Monitors soil moisture, temperature, pH and nutrients',
 '{
   "moisture_pct":  {"unit": "%",    "label": "Moisture",     "range": [0, 100]},
   "temperature_c": {"unit": "°C",   "label": "Temperature",  "range": [-20, 60]},
   "ph":            {"unit": "pH",   "label": "pH",           "range": [0, 14]},
   "nitrogen_ppm":  {"unit": "ppm",  "label": "Nitrogen",     "range": [0, 1000]},
   "phosphorus_ppm":{"unit": "ppm",  "label": "Phosphorus",   "range": [0, 1000]},
   "potassium_ppm": {"unit": "ppm",  "label": "Potassium",    "range": [0, 1000]}
 }'::jsonb),

('water_quality', 'Water Quality Monitor',
 'Monitors pH, turbidity, dissolved oxygen and temperature',
 '{
   "ph":            {"unit": "pH",    "label": "pH",               "range": [0, 14]},
   "turbidity_ntu": {"unit": "NTU",   "label": "Turbidity",        "range": [0, 1000]},
   "dissolved_o2":  {"unit": "mg/L",  "label": "Dissolved Oxygen", "range": [0, 20]},
   "temperature_c": {"unit": "°C",    "label": "Temperature",      "range": [-2, 50]},
   "conductivity":  {"unit": "μS/cm", "label": "Conductivity",     "range": [0, 10000]},
   "tds_ppm":       {"unit": "ppm",   "label": "Total Dissolved Solids", "range": [0, 2000]}
 }'::jsonb),

('noise', 'Noise Monitor',
 'Monitors ambient sound levels and frequency',
 '{
   "db_avg":        {"unit": "dB",   "label": "Average Level",  "range": [0, 140]},
   "db_peak":       {"unit": "dB",   "label": "Peak Level",     "range": [0, 140]},
   "db_min":        {"unit": "dB",   "label": "Minimum Level",  "range": [0, 140]}
 }'::jsonb),

('environment', 'Environment Monitor',
 'General purpose temperature, humidity and pressure monitoring',
 '{
   "temperature_c": {"unit": "°C",   "label": "Temperature", "range": [-40, 85]},
   "humidity_pct":  {"unit": "%RH",  "label": "Humidity",    "range": [0, 100]},
   "pressure_hpa":  {"unit": "hPa",  "label": "Pressure",    "range": [300, 1100]},
   "dew_point_c":   {"unit": "°C",   "label": "Dew Point",   "range": [-40, 60]}
 }'::jsonb);

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
  Replace carbon filters every 3-6 months in high VOC environments.'),

('air_quality', 'context', 'Almaty Kazakhstan Air Quality Context',
 'Almaty has severe winter air pollution primarily from coal heating, vehicle emissions and geography.
  Winter PM2.5 levels regularly reach 5-18x WHO guidelines.
  Key pollutants: PM2.5, PM10, NO2, SO2, CO, H2S.
  Pollution peaks: November to February, worst in temperature inversions.
  Comparison: Brisbane (Annerley) typical PM2.5: 5-10 μg/m³ (Good).
  Almaty winter typical PM2.5: 50-150 μg/m³ (Unhealthy to Very Unhealthy).'),

('soil', 'thresholds', 'Soil Health Guidelines',
 'Optimal soil conditions for general vegetable gardening:
  Moisture: 40-60% for most vegetables, 50-70% for leafy greens.
  pH: 6.0-7.0 optimal for most vegetables. Below 6.0 is acidic, above 7.0 is alkaline.
  Nitrogen: 20-40 ppm adequate for most crops.
  Phosphorus: 15-30 ppm adequate for most crops.
  Potassium: 100-150 ppm adequate for most crops.
  Temperature: 10-30°C optimal for root activity.'),

('water_quality', 'thresholds', 'Drinking Water Quality Guidelines',
 'WHO drinking water quality guidelines:
  pH: 6.5-8.5 acceptable range.
  Turbidity: Below 1 NTU ideal, below 4 NTU acceptable.
  Dissolved oxygen: Above 6 mg/L good for aquatic life.
  TDS: Below 600 ppm acceptable, below 300 ppm ideal.
  Conductivity: Below 400 μS/cm ideal for drinking water.'),

('noise', 'thresholds', 'Noise Level Guidelines',
 'WHO noise guidelines for health:
  Below 30 dB: Very quiet, suitable for sleeping.
  30-40 dB: Quiet, suitable for bedrooms at night.
  40-55 dB: Moderate, typical office environment.
  55-70 dB: Loud, prolonged exposure causes stress.
  70-85 dB: Very loud, hearing damage risk with prolonged exposure.
  Above 85 dB: Dangerous, hearing protection required.
  WHO recommends night noise below 40 dB for sleep.');
