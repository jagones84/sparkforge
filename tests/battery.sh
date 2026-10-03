#!/usr/bin/env bash
# SparkForge regression battery — NINE tests, one command.
#
# Properties:
#   * isolated: every SPARKFORGE_* data dir points at a throwaway temp dir, so the
#     battery NEVER touches the live transcripts, graphs, runs or the events DB,
#     and never leaves sessions in the WebUI;
#   * deterministic + fast: no live model, no network;
#   * one gate: exit code 0 only if every suite passes.
#
# Run:  bash tests/battery.sh
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT" || exit 1

TMP="$(mktemp -d "${TMPDIR:-/tmp}/sf-battery-XXXXXX")"
# JAG-207: keep bytecode in a fresh temp prefix — a stale __pycache__ (easy on an
# SMB/network share where mtimes lag) once made a fixed test fail. Never again.
export PYTHONPYCACHEPREFIX="$TMP/pyc"
export SPARKFORGE_CONFIG_DIR="$TMP/cfg"
export SPARKFORGE_SESSIONS_DIR="$TMP/sessions"
export SPARKFORGE_DB="$TMP/events.db"
export SPARKFORGE_GRAPH_DIR="$TMP/graphs"   # taskgraph appends "graphs" itself
export SPARKFORGE_EDITS_DIR="$TMP/edits"
export SPARKFORGE_RUNS_DIR="$TMP/runs"
mkdir -p "$SPARKFORGE_CONFIG_DIR" "$SPARKFORGE_SESSIONS_DIR" \
         "$SPARKFORGE_GRAPH_DIR" "$SPARKFORGE_EDITS_DIR" "$SPARKFORGE_RUNS_DIR"

TESTS="v140_subagent_todos v177_session_delete_cascade v183_chat_core v195_hard v198_skills_tools_awareness v204_memory_governance v205_heldout_gate v206_task_auditor v207_abuse_hard"
fail=0
for t in $TESTS; do
  echo "=== $t ==="
  if python3 "tests/$t.py"; then
    echo "PASS $t"
  else
    echo "FAIL $t"
    fail=1
  fi
done
rm -rf "$TMP"

if [ "$fail" -eq 0 ]; then
  echo "=== battery: 9/9 GREEN ==="
else
  echo "=== battery: FAILURES (see above) ==="
fi
exit "$fail"
