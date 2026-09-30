#!/bin/bash
# JAG-58 GREEN — restart harness and re-run acceptance
set -uo pipefail
systemctl --user restart sparkforge.service
sleep 5
systemctl --user is-active sparkforge.service
python3 - <<'PY'
import pathlib
for p in ("tests/v072_tool_use_acceptance.py", "api_v02.py", "server.py"):
    fp = pathlib.Path("/home/jagones/Repositories/sparkforge") / p
    b = fp.read_bytes().replace(b"\r\n", b"\n")
    fp.write_bytes(b)
print("CRLF stripped: test + api_v02 + server")
PY
cd /home/jagones/Repositories/sparkforge
export SPARKFORGE_TOKEN=REDACTED-COMPROMISED-TOKEN
timeout 900 python3 tests/v072_tool_use_acceptance.py --base http://127.0.0.1:8790 2>&1 | tail -40
