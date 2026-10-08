#!/usr/bin/env bash
# SparkForge regression battery — Auto-discovered tests.
# Run:  bash tests/battery.sh
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT" || exit 1

TMP="$(mktemp -d "${TMPDIR:-/tmp}/sf-battery-XXXXXX")"
export PYTHONPYCACHEPREFIX="$TMP/pyc"
export SPARKFORGE_CONFIG_DIR="$TMP/cfg"
export SPARKFORGE_SESSIONS_DIR="$TMP/sessions"
export SPARKFORGE_DB="$TMP/events.db"
export SPARKFORGE_GRAPH_DIR="$TMP/graphs"
export SPARKFORGE_EDITS_DIR="$TMP/edits"
export SPARKFORGE_RUNS_DIR="$TMP/runs"
export SPARKFORGE_ROLES_DIR="$TMP/roles"
export SPARKFORGE_COSTS_DIR="$TMP/costs"
export SPARKFORGE_PRICES_FILE="$TMP/prices.json"
mkdir -p "$SPARKFORGE_CONFIG_DIR" "$SPARKFORGE_SESSIONS_DIR" \
         "$SPARKFORGE_GRAPH_DIR" "$SPARKFORGE_EDITS_DIR" "$SPARKFORGE_RUNS_DIR" \
         "$SPARKFORGE_ROLES_DIR" "$SPARKFORGE_COSTS_DIR"

fail=0
total=0
pass=0

# Auto-discover tests in tests/acceptance
for t in tests/acceptance/v*.py; do
  total=$((total + 1))
  name=$(basename "$t" .py)
  echo "=== $name ==="
  if python3 "$t"; then
    echo "PASS $name"
    pass=$((pass + 1))
  else
    echo "FAIL $name"
    fail=1
  fi
done

rm -rf "$TMP"

if [ "$fail" -eq 0 ]; then
  echo "=== battery: $pass/$total GREEN ==="
else
  echo "=== battery: $pass/$total (FAILURES — see above) ==="
fi
exit "$fail"
