#!/bin/bash
cd /home/jagones/Repositories/sparkforge
python3 -m py_compile server.py context_engine.py memory.py providers.py || { echo COMPILE_FAIL; exit 1; }
echo COMPILE_OK
for t in tests/v074_context.py tests/v075_providers.py; do
  out=$(timeout 90 python3 "$t" 2>&1); rc=$?
  tail=$(printf '%s\n' "$out" | tail -n 1)
  if [ $rc -eq 0 ]; then echo "PASS $t :: $tail"; else echo "FAIL $t (rc=$rc) :: $tail"; fi
done
systemctl --user restart sparkforge
sleep 7
echo -n "service: "; systemctl --user is-active sparkforge
TOK="REDACTED-COMPROMISED-TOKEN"
SID=$(python3 -c "import sys;sys.path.insert(0,'.');import server;print((server.list_sessions() or [{'id':''}])[0]['id'])")
echo "--- /api/context default (local 262k) ---"
curl -s -H "Authorization: Bearer $TOK" "http://127.0.0.1:8790/api/context?session=$SID" | python3 -c "import sys,json;d=json.load(sys.stdin);print('used=%s budget=%s pct=%s'%(d.get('tokens_used'),d.get('budget_tokens'),d.get('pct')))"
echo "--- /api/context openrouter z-ai/glm-5.3-flash (live window) ---"
curl -s -H "Authorization: Bearer $TOK" "http://127.0.0.1:8790/api/context?session=$SID&model=openrouter:z-ai/glm-5.3-flash" | python3 -c "import sys,json;d=json.load(sys.stdin);print('used=%s budget=%s pct=%s'%(d.get('tokens_used'),d.get('budget_tokens'),d.get('pct')))"
echo "--- /api/providers openrouter windows ---"
curl -s -H "Authorization: Bearer $TOK" "http://127.0.0.1:8790/api/providers" | python3 -c "import sys,json;d=json.load(sys.stdin);p=[x for x in d['providers'] if x['id']=='openrouter'][0];print([(m['id'],m['context_length']) for m in p['models'][:6]])"
