# Sense Platform

[![CI/CD](https://github.com/ryandau/sense-platform/actions/workflows/deploy.yml/badge.svg)](https://github.com/ryandau/sense-platform/actions/workflows/deploy.yml)
![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)
![Ruff](https://img.shields.io/badge/code_style-Ruff-D7FF64?logo=ruff&logoColor=black)

Sensor-agnostic IoT data ingestion platform. Accepts readings from any device type (air quality, soil, water, noise, environment), stores them in PostgreSQL with pgvector, and serves a live visualisation frontend.

## Architecture

```mermaid
flowchart LR
  sensor[Sensor Device] -->|POST /ingest| apigw[API Gateway]
  apigw --> lambda[Lambda · FastAPI]
  lambda --> rds[(PostgreSQL)]
  browser[Browser] -.->|loads page| s3[S3 Frontend]
  browser -->|GET /latest| apigw
```

All infrastructure is defined in CDK (TypeScript). The database sits in isolated VPC subnets with no public access. Secrets are managed via AWS Secrets Manager — no plaintext credentials in environment variables or CI. SSL is enforced on all database connections.

## Repo structure

```
sense-platform/
├── backend/                Python application code
│   ├── app/api/ingest.py     FastAPI ingest API (Lambda handler)
│   ├── requirements.txt      Python dependencies
│   └── tests/                Unit tests
├── frontend/               Static frontend
│   └── index.html            Single-page visualisation dashboard
├── scripts/                Helper scripts
│   ├── bastion.sh            Bastion start/stop/creds/status
│   └── faker.sh              Sensor data simulator
├── infrastructure/         AWS CDK stack
│   ├── lib/                  Stack definition
│   ├── lambda/               Migration Lambda source
│   └── bin/                  CDK app entry point
└── .github/workflows/      CI/CD pipeline
```

## Prerequisites

- AWS account with CDK bootstrapped
- Node.js 22+
- [AWS CLI](https://docs.aws.amazon.com/cli/latest/userguide/install-cliv2.html) and [Session Manager plugin](https://docs.aws.amazon.com/systems-manager/latest/userguide/session-manager-working-with-install-plugin.html) (for database access)
- Custom domain (optional)

## Deploy

Add repository secrets (`AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_ACCOUNT_ID`) then trigger via GitHub Actions:

**Actions** > **Sense Platform CI/CD** > **Run workflow**

This provisions the full stack: VPC, RDS, Lambdas, API Gateway, S3 frontend bucket, bastion host, and Secrets Manager entries.

Backend code and frontend deploy automatically on every push to `main`.

## API usage

```bash
# Get the API URL from stack outputs
aws cloudformation describe-stacks \
  --stack-name SensePlatformStack \
  --query 'Stacks[0].Outputs[?OutputKey==`ApiUrl`].OutputValue' \
  --output text

# Get your API key
aws secretsmanager get-secret-value \
  --secret-id sense-platform/api-key \
  --query SecretString --output text

# Send a reading
curl -X POST https://<api-url>/v1/ingest \
  -H "Content-Type: application/json" \
  -H "X-API-Key: <your-api-key>" \
  -d '{
    "device_id": "sensor-001",
    "type_slug": "air_quality",
    "latitude": -27.47,
    "longitude": 153.03,
    "data": {"pm2_5": 8.3, "co2_ppm": 420, "temperature_c": 24.5}
  }'
```

## View the dashboard

```bash
aws cloudformation describe-stacks \
  --stack-name SensePlatformStack \
  --query 'Stacks[0].Outputs[?OutputKey==`FrontendUrl`].OutputValue' \
  --output text
```

Open this URL in your browser. The dashboard auto-discovers available devices from the API — no manual configuration needed.

### Custom domain (optional)

Set `frontendDomain` in `cdk.json` to your domain (this names the S3 bucket, configures CORS, and sets the display name), redeploy infrastructure, then point a CNAME to the S3 website URL from the stack outputs. DNS only — no proxy (e.g. Cloudflare proxy off).

### Endpoints

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/ingest` | API key | Submit a sensor reading |
| GET | `/health` | None | Health check |
| GET | `/devices` | None | List all registered devices |
| GET | `/devices/{id}/latest` | None | Latest reading for a device |
| GET | `/devices/{id}/history` | None | Reading history (limit=100) |
| GET | `/types` | None | List supported device types |

## Supported device types

| Slug | Name | Key fields |
|------|------|------------|
| `air_quality` | Air Quality Monitor | pm2_5, pm10_0, co2_ppm, voc_index, temperature_c, humidity_pct |
| `soil` | Soil Sensor | moisture_pct, temperature_c, ph, nitrogen_ppm |
| `water_quality` | Water Quality Monitor | ph, turbidity_ntu, dissolved_o2, temperature_c |
| `noise` | Noise Monitor | db_avg, db_peak, db_min |
| `environment` | Environment Monitor | temperature_c, humidity_pct, pressure_hpa |

## Database access

The RDS instance is in an isolated subnet. A helper script handles bastion startup, port forwarding, and credentials:

```bash
./scripts/bastion.sh start    # Start bastion + port forward (localhost:5432)
./scripts/bastion.sh creds    # Print DB credentials for your client
./scripts/bastion.sh stop     # Stop the bastion when done
./scripts/bastion.sh status   # Check if bastion is running
```

Connect your database client (e.g. TablePlus) to `localhost:5432` using the credentials from `creds`.

## Running tests

```bash
pip install -r backend/requirements.txt pytest ruff
pytest backend/tests/ -v
ruff check backend/
```

## License

MIT
