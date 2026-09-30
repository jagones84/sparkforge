#!/bin/bash
# JAG-58 — dump raw tool-use evidence
python3 - <<'PY'
import json
d = json.load(open("/home/jagones/Repositories/sparkforge/data/v072-tool-use.json"))
for r in d["results"]:
    print("\n===", r["check"], "->", "PASS" if r["ok"] else "FAIL")
    print("   evidence:", r["evidence"])
    if r.get("tool_calls"):
        print("   tool_calls:", json.dumps(r["tool_calls"], indent=2)[:1200])
PY
echo
echo "=== T1: full chat/stream event trace (what tool did chat call?) ==="
python3 - <<'PY'
import json, urllib.request, os
base="http://127.0.0.1:8790"
tok="REDACTED-COMPROMISED-TOKEN"
body=json.dumps({"message":"Usa i tuoi strumenti per elencarmi le categorie di skill, poi dimmi quanti tool hai."}).encode()
req=urllib.request.Request(base+"/api/chat/stream", data=body, headers={"Authorization":"Bearer "+tok,"Content-Type":"application/json"}, method="POST")
with urllib.request.urlopen(req, timeout=300) as r:
    for raw in r:
        line=raw.decode("utf-8","replace").rstrip("\n")
        if line.startswith("event:") or line.startswith("data:"):
            print(line[:400])
PY
