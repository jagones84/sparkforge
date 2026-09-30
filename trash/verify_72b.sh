#!/bin/bash
cd /home/jagones/Repositories/sparkforge
python3 -m py_compile server.py context_engine.py providers.py || { echo COMPILE_FAIL; exit 1; }
echo COMPILE_OK
echo "== targeted acceptance =="
for t in tests/v073_hooks.py tests/v074_context.py tests/v075_providers.py tests/v06_taskgraph.py; do
  out=$(timeout 120 python3 "$t" 2>&1); rc=$?
  tail=$(printf '%s\n' "$out" | tail -n 1)
  if [ $rc -eq 0 ]; then echo "PASS $t :: $tail"; else echo "FAIL $t (rc=$rc) :: $tail"; fi
done
echo "== restart + live endpoints =="
systemctl --user restart sparkforge
sleep 5
echo -n "service: "; systemctl --user is-active sparkforge
SID=$(python3 -c "import sys;sys.path.insert(0,'.');import server;print((server.list_sessions() or [{'id':''}])[0]['id'])")
echo "session=$SID"
TOK="REDACTED-COMPROMISED-TOKEN"
echo "--- /api/context (default model) ---"
curl -s -H "Authorization: Bearer $TOK" "http://127.0.0.1:8790/api/context?session=$SID"
echo
echo "--- /api/context (openrouter model => smaller declared window) ---"
curl -s -H "Authorization: Bearer $TOK" "http://127.0.0.1:8790/api/context?session=$SID&model=openrouter:z-ai/glm-5.3-flash"
echo
echo "--- /api/providers (ids only) ---"
curl -s -H "Authorization: Bearer $TOK" "http://127.0.0.1:8790/api/providers" | python3 -c "import sys,json;d=json.load(sys.stdin);print([(p['id'],p['available'],len(p['models'])) for p in d['providers']])"
