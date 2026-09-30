#!/usr/bin/env python3
"""Deny the currently-pending approval so the stuck run can continue."""
import json
import urllib.request

BASE = "http://127.0.0.1:8790"
H = {"Authorization": "Bearer REDACTED-COMPROMISED-TOKEN",
     "Content-Type": "application/json"}

req = urllib.request.Request(BASE + "/api/approvals", headers=H)
with urllib.request.urlopen(req, timeout=30) as r:
    d = json.loads(r.read().decode())
pend = [x for x in (d.get("approvals") or []) if x.get("status") == "pending"]
print("pending:", [(x["id"], x["tool"], x.get("run_id")) for x in pend])
for x in pend:
    body = json.dumps({"decision": "deny", "by": "operator"}).encode()
    req = urllib.request.Request(BASE + "/api/approvals/" + x["id"], data=body,
                                 headers=H, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            print("denied", x["id"], "->", r.status, r.read().decode()[:200])
    except Exception as e:
        print("err", x["id"], e)
