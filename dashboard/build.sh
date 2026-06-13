#!/usr/bin/env bash
# Build the Mundix360 dashboard SPA (frontend) into frontend/dist,
# which is served by the FastAPI backend. Idempotent and safe to run
# on every deploy / boot.
#
# The build goes into a STAGING directory and is swapped into place only
# after it succeeds. This matters because vite empties its outDir at the
# START of the build: building straight into the live dist/ would leave the
# dashboard blank for the whole (multi-minute) build while users are browsing.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FRONTEND="$HERE/frontend"
STAGING="$FRONTEND/.dist-staging"

cd "$FRONTEND"

# Install deps only when needed (no node_modules or package.json changed).
if [[ ! -d node_modules ]] || [[ package-lock.json -nt node_modules ]]; then
  echo "[build] installing frontend dependencies..."
  npm ci --no-audit --no-fund 2>/dev/null || npm install --no-audit --no-fund
fi

echo "[build] compiling SPA into staging..."
rm -rf "$STAGING"
# --outDir overrides vite.config; the live dist/ is never touched here.
npm run build -- --outDir .dist-staging --emptyOutDir

echo "[build] swapping dist into place..."
rm -rf "$FRONTEND/dist.old"
if [[ -d "$FRONTEND/dist" ]]; then
  mv "$FRONTEND/dist" "$FRONTEND/dist.old"
fi
mv "$STAGING" "$FRONTEND/dist"
rm -rf "$FRONTEND/dist.old"

echo "[build] done -> $FRONTEND/dist"
