#!/usr/bin/env bash
# Usage: ./deploy.sh user@hostname
set -euo pipefail

SERVER="${1:?Usage: ./deploy.sh user@hostname}"
REMOTE_DIR="/srv/socialhockey"

echo "==> Syncing project to $SERVER:$REMOTE_DIR ..."
rsync -avz --delete \
  --exclude='.git' \
  --exclude='.venv' \
  --exclude='__pycache__' \
  --exclude='*.pyc' \
  --exclude='*.pyo' \
  --exclude='.env' \
  --exclude='.pytest_cache' \
  --exclude='.mypy_cache' \
  . "$SERVER:$REMOTE_DIR/"

echo "==> Checking .env exists on server ..."
if ! ssh "$SERVER" "test -f $REMOTE_DIR/.env"; then
  echo ""
  echo "  WARNING: $REMOTE_DIR/.env not found on server."
  echo "  Copy .env.example, fill in the values, and re-run:"
  echo "    scp .env.example $SERVER:$REMOTE_DIR/.env"
  echo "    ssh $SERVER 'nano $REMOTE_DIR/.env'"
  echo ""
  exit 1
fi

echo "==> Building and starting containers ..."
ssh "$SERVER" "cd $REMOTE_DIR && docker compose up -d --build"

echo "==> Waiting for health check ..."
sleep 5
ssh "$SERVER" "cd $REMOTE_DIR && docker compose ps"

APP_URL=$(ssh "$SERVER" "grep -E '^BASE_URL=' $REMOTE_DIR/.env | cut -d= -f2-" 2>/dev/null || true)
echo ""
echo "==> Deployed! App running at: ${APP_URL:-https://$SERVER}"
