-- Runs automatically the first time the Postgres volume is created.
-- Guarantees the extensions exist before any schema/data is loaded.
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
