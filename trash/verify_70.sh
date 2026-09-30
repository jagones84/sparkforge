#!/bin/bash
cd /home/jagones/Repositories/sparkforge
python3 -m py_compile server.py context_engine.py api_v02.py hooks.py tools.py sandbox.py || { echo COMPILE_FAIL; exit 1; }
echo COMPILE_OK
echo "== v074 context acceptance =="
python3 tests/v074_context.py
echo "== restart + live /api/context =="
systemctl --user restart sparkforge
sleep 5
echo -n "service: "; systemctl --user is-active sparkforge
SID=$(python3 -c "import sys;sys.path.insert(0,'.');import server;print((server.list_sessions() or [{'id':''}])[0]['id'])")
echo "session=$SID"
curl -s -H "Authorization: Bearer REDACTED-COMPROMISED-TOKEN" "http://127.0.0.1:8790/api/context?session=$SID"
echo
