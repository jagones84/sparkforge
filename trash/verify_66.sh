#!/bin/bash
cd /home/jagones/Repositories/sparkforge
python3 -m py_compile taskgraph.py server.py api_v02.py context_engine.py || { echo COMPILE_FAIL; exit 1; }
echo COMPILE_OK
systemctl --user restart sparkforge
sleep 5
echo -n "service: "; systemctl --user is-active sparkforge
echo "== ctx budget from /api/context =="
curl -s -H "Authorization: Bearer REDACTED-COMPROMISED-TOKEN" "http://127.0.0.1:8790/api/context"
echo
python3 tests/v06_taskgraph.py 2>&1 | tail -n 22
