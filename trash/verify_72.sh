#!/bin/bash
cd /home/jagones/Repositories/sparkforge
python3 -m py_compile server.py context_engine.py api_v02.py hooks.py tools.py sandbox.py providers.py || { echo COMPILE_FAIL; exit 1; }
echo COMPILE_OK
echo "== full acceptance suite =="
fail=0
for t in tests/v0*.py; do
  out=$(python3 "$t" 2>&1); rc=$?
  tail=$(printf '%s\n' "$out" | tail -n 1)
  if [ $rc -eq 0 ]; then echo "PASS $t :: $tail"; else echo "FAIL $t :: $tail"; fail=1; fi
done
echo "SUITE_FAIL=$fail"
echo "== restart + live /api/context =="
systemctl --user restart sparkforge
sleep 5
echo -n "service: "; systemctl --user is-active sparkforge
SID=$(python3 -c "import sys;sys.path.insert(0,'.');import server;print((server.list_sessions() or [{'id':''}])[0]['id'])")
echo "session=$SID"
curl -s -H "Authorization: Bearer REDACTED-COMPROMISED-TOKEN" "http://127.0.0.1:8790/api/context?session=$SID"
echo
curl -s -H "Authorization: Bearer REDACTED-COMPROMISED-TOKEN" "http://127.0.0.1:8790/api/providers" | head -c 400
echo
