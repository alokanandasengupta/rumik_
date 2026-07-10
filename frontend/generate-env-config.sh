#!/bin/sh
# Regenerates env-config.js from the current environment. Run this once at
# container/process start (supervisord.conf does), before serving the
# frontend's static files.
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
echo "window.REACT_APP_BACKEND_URL = \"${REACT_APP_BACKEND_URL:-}\";" > "$DIR/env-config.js"
