#!/usr/bin/env bash
# Backwards-compatible shell entry point for the cross-platform Python demo.
set -Eeuo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"
exec python3 "$ROOT/examples/demo.py" "$@"
