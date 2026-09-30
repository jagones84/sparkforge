#!/bin/bash
cd /home/jagones/Repositories/sparkforge
python3 -m py_compile hooks.py tools.py server.py api_v02.py sandbox.py || { echo COMPILE_FAIL; exit 1; }
echo COMPILE_OK
echo "== hooks acceptance =="
python3 tests/v073_hooks.py
echo "== restart + /api/hooks =="
systemctl --user restart sparkforge
sleep 5
echo -n "service: "; systemctl --user is-active sparkforge
curl -s -H "Authorization: Bearer REDACTED-COMPROMISED-TOKEN" "http://127.0.0.1:8790/api/hooks"
echo
