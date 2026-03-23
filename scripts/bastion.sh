#!/bin/bash
# Sense Platform — Bastion helper
# Usage:
#   ./scripts/bastion.sh start    Start bastion + port forward (localhost:5432)
#   ./scripts/bastion.sh stop     Stop the bastion
#   ./scripts/bastion.sh creds    Print DB credentials
#   ./scripts/bastion.sh status   Check if bastion is running

set -e

STACK="SensePlatformStack"
REGION="ap-southeast-2"

get_output() {
  aws cloudformation describe-stacks \
    --stack-name "$STACK" \
    --region "$REGION" \
    --query "Stacks[0].Outputs[?OutputKey=='$1'].OutputValue" \
    --output text 2>/dev/null
}

BASTION_ID=$(get_output "BastionInstanceId")
DB_ENDPOINT=$(get_output "DbEndpoint")
DB_SECRET=$(get_output "DbSecretArn")

if [ -z "$BASTION_ID" ]; then
  echo "Could not find bastion ID in stack outputs."
  exit 1
fi

case "${1:-help}" in
  start)
    echo "Starting bastion ($BASTION_ID)..."
    aws ec2 start-instances --instance-ids "$BASTION_ID" --region "$REGION" --output text > /dev/null
    echo "Waiting for bastion to boot (~30s)..."
    aws ec2 wait instance-status-ok --instance-ids "$BASTION_ID" --region "$REGION"
    echo ""
    echo "Bastion is up. Starting port forward..."
    echo "  DB endpoint: $DB_ENDPOINT"
    echo "  Local:       localhost:5432"
    echo ""
    echo "Connect TablePlus to localhost:5432"
    echo "Run './scripts/bastion.sh creds' for username/password"
    echo "Press Ctrl+C to disconnect."
    echo ""
    aws ssm start-session \
      --target "$BASTION_ID" \
      --region "$REGION" \
      --document-name AWS-StartPortForwardingSessionToRemoteHost \
      --parameters "{\"host\":[\"$DB_ENDPOINT\"],\"portNumber\":[\"5432\"],\"localPortNumber\":[\"5432\"]}"
    ;;

  stop)
    echo "Stopping bastion ($BASTION_ID)..."
    aws ec2 stop-instances --instance-ids "$BASTION_ID" --region "$REGION" --output text > /dev/null
    echo "Bastion stopped."
    ;;

  creds)
    echo "DB credentials:"
    aws secretsmanager get-secret-value \
      --secret-id "$DB_SECRET" \
      --region "$REGION" \
      --query SecretString --output text | python3 -c "
import sys, json
s = json.load(sys.stdin)
print(f\"  Host:     localhost (via port forward)\")
print(f\"  Port:     5432\")
print(f\"  Database: {s.get('dbname', 'sense')}\")
print(f\"  Username: {s['username']}\")
print(f\"  Password: {s['password']}\")
"
    ;;

  status)
    STATE=$(aws ec2 describe-instances --instance-ids "$BASTION_ID" --region "$REGION" \
      --query 'Reservations[0].Instances[0].State.Name' --output text)
    echo "Bastion ($BASTION_ID): $STATE"
    echo "DB endpoint: $DB_ENDPOINT"
    ;;

  *)
    echo "Sense Platform — Bastion helper"
    echo ""
    echo "Usage:"
    echo "  ./scripts/bastion.sh start    Start bastion + port forward (localhost:5432)"
    echo "  ./scripts/bastion.sh stop     Stop the bastion"
    echo "  ./scripts/bastion.sh creds    Print DB credentials"
    echo "  ./scripts/bastion.sh status   Check if bastion is running"
    ;;
esac
