#!/usr/bin/env bash
# Longrun Mega Debug Suite
# This script executes the layers of the debugging stack:
# 1. Static Analysis (Ruff, Mypy, Bandit)
# 2. Battery (Unit/Acceptance Tests)
# 3. Property-Based Testing (Hypothesis)
# 4. Mutation Testing (Mutmut)

set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "=========================================="
echo "      LONGRUN MEGA DEBUG SUITE         "
echo "=========================================="

echo -e "\n[0] Environment Setup"
if [ ! -d ".venv" ]; then
    python3 -m venv .venv
fi
source .venv/bin/activate
pip install -q ruff mypy bandit mutmut hypothesis pytest

echo -e "\n[1] STATIC ANALYSIS"
echo "------------------------------------------"
echo "-> Running Ruff (Linter)..."
ruff check src/longrun || echo "Ruff found issues."

echo "-> Running Mypy (Type Checker)..."
mypy src/longrun --ignore-missing-imports || echo "Mypy found issues."

echo "-> Running Bandit (Security)..."
bandit -r src/longrun -ll -q || echo "Bandit found issues."

echo -e "\n[2] ACCEPTANCE TESTS (Battery)"
echo "------------------------------------------"
export PYTHONPATH="$ROOT"
bash tests/battery.sh || echo "Battery failed."

echo -e "\n[3] PROPERTY-BASED TESTS"
echo "------------------------------------------"
pytest tests/properties/ || echo "Property tests failed."

echo -e "\n[4] MUTATION TESTING"
echo "------------------------------------------"
# Scope to taskgraph.py as requested by user to keep it fast
echo "Running mutmut against src/longrun/taskgraph.py..."
# mutmut needs to know how to run tests. We configure it to run battery.sh
cat << 'EOF' > setup.cfg
[mutmut]
paths_to_mutate=src/longrun/taskgraph.py
runner=bash tests/battery.sh
EOF

mutmut run || echo "Mutmut found surviving mutations."
echo "Mutmut Results:"
mutmut results

echo "=========================================="
echo "      DEBUG SUITE EXECUTION COMPLETE      "
echo "=========================================="
