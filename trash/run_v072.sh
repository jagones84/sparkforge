#!/bin/bash
# JAG-58 — run the tool-use acceptance suite (TDD RED)
set -uo pipefail
cd /home/jagones/Repositories/sparkforge
python3 - <<'PY'
p = "tests/v072_tool_use_acceptance.py"
b = open(p, "rb").read().replace(b"\r\n", b"\n")
open(p, "wb").write(b)
print("CRLF stripped")
PY
export SPARKFORGE_TOKEN=REDACTED-COMPROMISED-TOKEN
timeout 900 python3 tests/v072_tool_use_acceptance.py --base http://127.0.0.1:8790 2>&1 | tail -70
