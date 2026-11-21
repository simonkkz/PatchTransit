#!/usr/bin/env bash
# Produce a complete, safe demo without touching an existing source checkout.
set -Eeuo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DIR="$(mktemp -d)"
trap 'rm -rf "$DIR"' EXIT
mkdir "$DIR/repo"
cd "$DIR/repo"
git init -q
git -c user.name=PatchTransit -c user.email=demo@example.invalid commit --allow-empty -qm 'demo base'
printf 'def calculate():\n    return 1\n' > calc.py
git add calc.py
git -c user.name=PatchTransit -c user.email=demo@example.invalid commit -qm 'add example'
printf 'def calculate():\n    return 2\n' > calc.py
git diff > "$DIR/old.patch"
printf 'def calculate():\n    return 3\n' > calc.py
git diff > "$DIR/new.patch"
git restore calc.py
mkdir -p "$ROOT/reports"
PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}" python3 -m patchtransit compare "$DIR/old.patch" "$DIR/new.patch" \
  --repo "$DIR/repo" --html "$ROOT/reports/demo.html" --json "$ROOT/reports/demo.json" --diff "$ROOT/reports/demo.diff"
echo "Open in a browser: $ROOT/reports/demo.html"
