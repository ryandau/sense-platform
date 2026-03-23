#!/bin/bash
# Sense Platform — Faker helper
# Usage:
#   ./scripts/faker.sh start      Start sending readings in background (every 60s)
#   ./scripts/faker.sh stop       Stop the background loop
#   ./scripts/faker.sh once       Send a single reading
#   ./scripts/faker.sh dry-run    Print payload without sending
#   ./scripts/faker.sh status     Check if faker is running
#   ./scripts/faker.sh list       List available fake devices

set -e

STACK="SensePlatformStack"
REGION="ap-southeast-2"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
FAKER_DIR="$PROJECT_DIR/faker"
PID_FILE="$SCRIPT_DIR/.faker.pid"

get_output() {
  aws cloudformation describe-stacks \
    --stack-name "$STACK" \
    --region "$REGION" \
    --query "Stacks[0].Outputs[?OutputKey=='$1'].OutputValue" \
    --output text 2>/dev/null
}

load_env() {
  API_URL=$(get_output "ApiUrl")
  if [ -z "$API_URL" ]; then
    echo "Could not find API URL in stack outputs."
    exit 1
  fi
  INGEST_URL="${API_URL}ingest"

  API_KEY=$(aws secretsmanager get-secret-value \
    --secret-id "sense-platform/api-key" \
    --region "$REGION" \
    --query SecretString --output text 2>/dev/null)
  if [ -z "$API_KEY" ]; then
    echo "Could not read API key from Secrets Manager."
    exit 1
  fi

  export INGEST_URL API_KEY
}

ensure_deps() {
  if ! python3 -c "import httpx" 2>/dev/null; then
    echo "Installing faker dependencies..."
    pip3 install -r "$FAKER_DIR/requirements.txt" --quiet
  fi
}

case "${1:-help}" in
  start)
    if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
      echo "Faker is already running (PID $(cat "$PID_FILE"))."
      exit 0
    fi
    load_env
    ensure_deps
    INTERVAL="${2:-60}"
    echo "Starting faker (every ${INTERVAL}s)..."
    echo "  Endpoint: $INGEST_URL"
    nohup bash -c "
      export INGEST_URL='$INGEST_URL' API_KEY='$API_KEY'
      while true; do
        python3 '$FAKER_DIR/faker.py' --once 2>&1 | while read line; do
          echo \"\$(date '+%H:%M:%S') \$line\"
        done
        sleep $INTERVAL
      done
    " > "$SCRIPT_DIR/.faker.log" 2>&1 &
    echo $! > "$PID_FILE"
    echo "Faker started (PID $!)."
    echo "  Logs: $SCRIPT_DIR/.faker.log"
    echo "  Stop: ./scripts/faker.sh stop"
    ;;

  stop)
    if [ -f "$PID_FILE" ]; then
      PID=$(cat "$PID_FILE")
      if kill -0 "$PID" 2>/dev/null; then
        kill "$PID" 2>/dev/null
        # Also kill child processes
        pkill -P "$PID" 2>/dev/null || true
        echo "Faker stopped (PID $PID)."
      else
        echo "Faker was not running."
      fi
      rm -f "$PID_FILE"
    else
      echo "Faker is not running."
    fi
    ;;

  once)
    load_env
    ensure_deps
    python3 "$FAKER_DIR/faker.py" --once "${@:2}"
    ;;

  send)
    FILE="${2:?Usage: ./scripts/faker.sh send <file.json>}"
    if [ ! -f "$FILE" ]; then
      echo "File not found: $FILE"
      exit 1
    fi
    load_env
    echo "Sending $FILE to $INGEST_URL"
    curl -s -X POST "$INGEST_URL" \
      -H "Content-Type: application/json" \
      -H "X-API-Key: $API_KEY" \
      -d @"$FILE" | python3 -m json.tool
    ;;

  dry-run)
    ensure_deps
    export INGEST_URL="https://example.com/ingest" API_KEY="dry-run"
    python3 "$FAKER_DIR/faker.py" --dry-run "${@:2}"
    ;;

  status)
    if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
      echo "Faker is running (PID $(cat "$PID_FILE"))."
      echo "Last log entries:"
      tail -5 "$SCRIPT_DIR/.faker.log" 2>/dev/null || echo "  (no logs yet)"
    else
      echo "Faker is not running."
      rm -f "$PID_FILE"
    fi
    ;;

  list)
    ensure_deps
    python3 "$FAKER_DIR/faker.py" --list
    ;;

  *)
    echo "Sense Platform — Faker helper"
    echo ""
    echo "Usage:"
    echo "  ./scripts/faker.sh start [interval]  Start sending readings in background (default: 60s)"
    echo "  ./scripts/faker.sh stop              Stop the background loop"
    echo "  ./scripts/faker.sh once              Send a single reading"
    echo "  ./scripts/faker.sh send <file.json>  Send a custom JSON payload"
    echo "  ./scripts/faker.sh dry-run           Print payload without sending"
    echo "  ./scripts/faker.sh status            Check if faker is running"
    echo "  ./scripts/faker.sh list              List available fake devices"
    ;;
esac
