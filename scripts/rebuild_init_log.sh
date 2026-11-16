#!/usr/bin/env bash
# Build the current two-source log/display-test ramdisk.
set -euo pipefail
COROT_SCRIPT_DIR="$(cd -- "$(dirname -- "$0")" && pwd -P)"
exec python3 "$COROT_SCRIPT_DIR/../tools/build-log-ramdisk.py" "$@"
