#!/usr/bin/env bash
# Teleport Demo Reset Script
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

echo "=== Teleport Demo Environment Reset ==="

echo "[i] Killing processes on ports 8765, 8766, 5173..."
for PORT in 8765 8766 5173; do
  PIDS=$(lsof -ti :$PORT 2>/dev/null || true)
  if [ -n "$PIDS" ]; then
    echo "[i] Terminating port $PORT (PIDs: $PIDS)"
    kill -9 $PIDS 2>/dev/null || true
  fi
done

echo "[i] Wiping .teleport-dev/..."
rm -rf "$REPO_ROOT/.teleport-dev"
mkdir -p "$REPO_ROOT/.teleport-dev/a" "$REPO_ROOT/.teleport-dev/b"

echo "[✓] State successfully reset."
if [ "$1" == "--start" ]; then
  echo "=== Launching Fresh Demo Agents ==="
  python3 -m teleport --port 8765 --home "$REPO_ROOT/.teleport-dev/a" --sim-profile default --name "Device A" &
  python3 -m teleport --port 8766 --home "$REPO_ROOT/.teleport-dev/b" --sim-profile arm64-lowspec --name "Device B" &
  echo "[✓] Fresh agents spawned. Launch UI with: npm run dev:ui"
fi

