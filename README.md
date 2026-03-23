# Sense Platform

[![CI/CD](https://github.com/ryandau/sense-platform/actions/workflows/deploy.yml/badge.svg)](https://github.com/ryandau/sense-platform/actions/workflows/deploy.yml)
![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)
![Ruff](https://img.shields.io/badge/code_style-Ruff-D7FF64?logo=ruff&logoColor=black)

Sensor-agnostic IoT platform. Ingests readings, computes derived metrics via EPA breakpoints, and stores RAG-ready content strings in PostgreSQL with pgvector. Deployed on AWS with a live dashboard.

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
│   ├── faker.sh              Sensor data simulator
│   └── faker/                Faker Python source and devices
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

## Deploy

See the [setup guide](docs/setup.md) for detailed IAM and secrets configuration.

Once secrets are configured, trigger via GitHub Actions:

**Actions** > **Sense Platform CI/CD** > **Run workflow**

This provisions the full stack: VPC, RDS, Lambdas, API Gateway, S3 frontend bucket, bastion host, and Secrets Manager entries.

Backend code and frontend deploy automatically on every push to `main`.

## API usage

```bash
# Get the API URL and API key
aws cloudformation describe-stacks \
  --stack-name SensePlatformStack \
  --query 'Stacks[0].Outputs[?OutputKey==`ApiUrl`].OutputValue' \
  --output text

aws secretsmanager get-secret-value \
  --secret-id sense-platform/api-key \
  --query SecretString --output text

# Send a reading
curl -X POST https://<api-url>/ingest \
  -H "Content-Type: application/json" \
  -H "X-API-Key: <your-api-key>" \
  -d '{
    "device_id": "sensor-001",
    "type_slug": "air_quality",
    "latitude": -27.47,
    "longitude": 153.03,
    "data": {"pm2_5": 8.3, "co2_ppm": 420, "temperature_c": 24.5}
  }'

# View the dashboard
aws cloudformation describe-stacks \
  --stack-name SensePlatformStack \
  --query 'Stacks[0].Outputs[?OutputKey==`FrontendUrl`].OutputValue' \
  --output text
```

Open the frontend URL in your browser. The dashboard auto-discovers devices from the API.

## Custom domain (optional)

1. Edit `frontendDomain` in [`infrastructure/cdk.json`](infrastructure/cdk.json) — replace the default with your domain
2. Redeploy infrastructure (**Actions** > **Run workflow**)
3. Create a CNAME DNS record pointing your domain to the `FrontendUrl` from stack outputs
4. Set your DNS provider to **DNS only** (no proxy) — S3 static hosting requires direct resolution

## Endpoints

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/ingest` | API key | Submit a sensor reading |
| GET | `/health` | None | Health check |
| GET | `/devices` | None | List all registered devices |
| GET | `/devices/{id}/latest` | None | Latest reading for a device |
| GET | `/devices/{id}/history` | None | Reading history (limit=100) |
| GET | `/types` | None | List supported device types |

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
