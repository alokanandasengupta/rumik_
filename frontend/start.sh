#!/bin/sh
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
"$DIR/generate-env-config.sh"
exec python3 -m http.server "${PORT:-3000}" --directory "$DIR"
