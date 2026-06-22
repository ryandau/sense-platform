# Self-Hosting Guide

This guide covers installing, configuring, and operating Sense Platform on your
own hardware with Docker Compose. The platform runs as two containers — the
application (API and dashboard) and a PostgreSQL database. The embedding
pipeline and the `/ask` endpoint require OpenAI and Anthropic API keys.

## Contents

- [Requirements](#requirements)
- [1. Configure](#1-configure)
- [2. Initialise the database](#2-initialise-the-database)
- [3. Start the application](#3-start-the-application)
- [4. Connect a device](#4-connect-a-device)
- [5. Remote access (optional)](#5-remote-access-optional)
- [6. MCP server (optional)](#6-mcp-server-optional)
- [Operations](#operations)
- [Troubleshooting](#troubleshooting)

## Requirements

- A host that remains powered on, such as a single-board computer, a small server, or a virtual machine
- Docker and Docker Compose ([installation instructions](https://docs.docker.com/engine/install/))
- For device ingestion, the sensor and the host on the same local network

## 1. Configure

Clone the repository and create a configuration file:

```bash
git clone <repository-url> sense-platform
cd sense-platform
cp .env.example .env
```

Edit `.env` and set, at minimum, `SENSE_API_KEY` and `PGPASSWORD`. A strong API
key can be generated with:

```bash
openssl rand -hex 24
```

Set `OPENAI_API_KEY` and `ANTHROPIC_API_KEY`. They power the embedding pipeline
and the `/ask` endpoint, and the application will not start without them.

## 2. Initialise the database

Start the database and load the schema:

```bash
docker compose up -d db
./scripts/db-setup.sh fresh
```

`fresh` creates the schema and seed data: device types, the knowledge base, and
the AQI breakpoints. To restore an existing backup instead, use:

```bash
./scripts/db-setup.sh restore path/to/backup.sql.gz
```

## 3. Start the application

```bash
docker compose up -d api
```

The dashboard and API are now available at `http://localhost:8000`, or at
`http://<host-ip>:8000` from other devices on the network.

## 4. Connect a device

Sensors send readings to the application over HTTP on the local network.

1. **Find the host's local IP address** (for example `192.168.1.50`). It is
   usually listed in your router's connected-devices view or in your operating
   system's network settings. Assigning a static or reserved address ensures it
   does not change.

2. **Point the device at the host.** For the reference M5Stack firmware, edit
   `firmware/airq/data/db.json`:

   ```json
   "endpoint": "http://192.168.1.50:8000",
   "api_key": "<the SENSE_API_KEY from your .env>"
   ```

3. **Apply the configuration** to the device. See
   [firmware/README.md](../firmware/README.md) for the firmware build and flash
   steps.

The device posts readings to `<endpoint>/ingest`. Confirm they are arriving with
`docker compose logs -f api` or on the dashboard.

## 5. Remote access (optional)

By default the platform is reachable only on the local network. To access the
dashboard remotely without exposing inbound ports, use a Cloudflare Tunnel:

1. In the Cloudflare Zero Trust dashboard, create a tunnel and add a public
   hostname routed to `http://api:8000`.
2. Add the tunnel token to `.env` as `TUNNEL_TOKEN`.
3. Start the tunnel container:

   ```bash
   docker compose --profile tunnel up -d cloudflared
   ```

The dashboard is then served over HTTPS at your chosen hostname, while devices
continue to post to the local address.

## 6. MCP server (optional)

The platform can expose its data to [Model Context Protocol](https://modelcontextprotocol.io)
clients (such as Claude Desktop) as tools: `list_devices`, `latest_reading`,
`reading_history`, `aqi_status`, and `ask`.

Over HTTP (for networked clients):

```bash
docker compose --profile mcp up -d mcp     # serves http://localhost:8001/mcp
```

Over stdio (for a local client like Claude Desktop), run the server directly and
add it to the client's MCP configuration, for example:

```json
{
  "mcpServers": {
    "sense-platform": {
      "command": "python",
      "args": ["-m", "app.mcp_server"],
      "cwd": "/path/to/sense-platform/backend",
      "env": { "MCP_TRANSPORT": "stdio" }
    }
  }
}
```

The server reads the same `.env` configuration and requires the AI keys.

## Operations

**Apply changed configuration or AI keys.** Editing `.env` requires recreating
the application container so it reads the new values:

```bash
docker compose up -d --force-recreate api
```

**Update to a new version.**

```bash
git pull
docker compose up -d --build api
```

Data is stored in the `sense-db-data` Docker volume and is preserved across
updates and rebuilds.

**Create a backup.**

```bash
set -a; . ./.env; set +a
docker compose exec -T db pg_dump -U "$PGUSER" "$PGDATABASE" | gzip > backups/sense-$(date +%F).sql.gz
```

Restore a backup with `./scripts/db-setup.sh restore <file>`.

## Troubleshooting

**A device cannot connect.** Confirm the device and host are on the same
network, and that the API is reachable from another machine on it:
`curl http://<host-ip>:8000/health`.

**The application exits on startup with a configuration error.** A required
setting is missing — typically `SENSE_API_KEY`, `OPENAI_API_KEY`, or
`ANTHROPIC_API_KEY`. The log lists which. Set them in `.env` and restart with
`docker compose up -d --force-recreate api`.

**`/ask` returns 500 with "Connection error".** The application container cannot
reach the OpenAI or Anthropic APIs. Confirm the host firewall permits outbound
HTTPS and that the container can resolve DNS:

```bash
docker compose exec api python -c "import socket; print(socket.gethostbyname('api.openai.com'))"
```

The `dns` setting on the `api` service in `docker-compose.yml` provides resolvers
for environments that do not forward container DNS.

**Check service status.** `curl http://localhost:8000/health` reports the service
state and whether the AI layer is configured.
