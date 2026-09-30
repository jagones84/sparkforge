#!/usr/bin/env python3
"""JAG-58c — why the agent hangs: approvals timeout + pending list."""
import json
import urllib.request

BASE = "http://127.0.0.1:8790"
H = {"Authorization": "Bearer REDACTED-COMPROMISED-TOKEN"}


def get(p):
    req = urllib.request.Request(BASE + p, headers=H)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())


print("=== approvals config ===")
try:
    print(json.dumps(get("/api/config"), indent=2)[:1200])
except Exception as e:
    print("err /api/config:", e)

print("\n=== registry approvals policy (from /api/tools) ===")
d = get("/api/tools")
tools = d.get("tools") or d.get("catalog") or d
for t in tools:
    if isinstance(t, dict):
        print(f"  {t.get('name'):24s} approval={t.get('approval')}")

print("\n=== recent approvals ===")
ap = get("/api/approvals")
for x in (ap.get("approvals") or [])[-12:]:
    print(f"  {x.get('status'):14s} {x.get('tool'):22s} run={x.get('run_id')} id={x.get('id')}")

print("\n=== pending count ===")
print("pending:", sum(1 for x in (ap.get("approvals") or [])
                     if x.get("status") == "pending"))
