#!/bin/bash
TOKEN=REDACTED-COMPROMISED-TOKEN
echo "--- router :8080 ---"
curl -s -m 5 http://127.0.0.1:8080/v1/models | head -c 300
echo
echo "--- /api/status ---"
curl -s -m 5 -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8790/api/status | head -c 500
echo
echo "--- feed :8787 status.json (model) ---"
curl -s -m 5 "http://100.102.61.23:8787/status.json" | python3 -c "import sys,json;d=json.load(sys.stdin);print({k:d.get(k) for k in ('ts','gpu','memory')})" 2>/dev/null | head -c 400
echo
echo "--- pyspy: threads busy in server ---"
ps -o pid,etimes,pcpu,cmd -p "$(pgrep -f 'server.py' | head -n1)" 2>/dev/null
