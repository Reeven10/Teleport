#!/bin/bash
# Double-click to start Teleport on this Mac (or run it on Linux). The first run installs it.
cd "$(dirname "$0")" || exit 1

if [ ! -x .venv/bin/python ]; then
  echo "First start: installing Teleport. This takes a few minutes..."
  PY=$(command -v python3.12 || command -v python3.11 || command -v python3)
  if [ -z "$PY" ]; then
    echo "Python 3.11 or newer is needed: install it from https://www.python.org/downloads/"
    read -r -p "Press Enter to close." _; exit 1
  fi
  "$PY" -m venv .venv && .venv/bin/python -m pip install --upgrade pip >/dev/null \
    && .venv/bin/python -m pip install -e agent || { read -r -p "Install failed. Press Enter to close." _; exit 1; }
fi

if [ ! -f ui/dist/index.html ]; then
  if ! command -v npm >/dev/null; then
    echo "Node.js is needed once to build the dashboard: install it from https://nodejs.org/ and start again."
    read -r -p "Press Enter to close." _; exit 1
  fi
  echo "Building the dashboard..."
  npm install && npm run build || { read -r -p "Build failed. Press Enter to close." _; exit 1; }
fi

exec .venv/bin/python -m teleport.launch "$@"
