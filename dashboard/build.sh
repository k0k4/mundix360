#!/usr/bin/env bash
# Build the Mundix360 dashboard SPA (frontend) into frontend/dist,
# which is served by the FastAPI backend. Idempotent and safe to run
# on every deploy / boot.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FRONTEND="$HERE/frontend"

cd "$FRONTEND"

# Install deps only when needed (no node_modules or package.json changed).
if [[ ! -d node_modules ]] || [[ package-lock.json -nt node_modules ]]; then
  echo "[build] installing frontend dependencies..."
  npm ci --no-audit --no-fund 2>/dev/null || npm install --no-audit --no-fund
fi

echo "[build] compiling SPA..."
npm run build

echo "[build] done -> $FRONTEND/dist"
