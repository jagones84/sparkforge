#!/usr/bin/env python3
"""JAG-68 live test: start a long tool on the server, then STOP it.

POST /api/tools/call {shell: "sleep 120"} in a background thread; approve the
gate so the subprocess really starts; confirm it shows in /api/tools/running;
POST /api/tools/cancel; the call must return quickly with cancelled=True.
"""
import json
import threading
import time
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8790"
TOK = "REDACTED-COMPROMISED-TOKEN"


def req(path, body=None, method="POST", timeout=60):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(BASE + path, data=data, method=method,
                               headers={"Authorization": "Bearer " + TOK,
                                        "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            return json.loads(resp.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        return {"http_error": e.code, "body": e.read().decode()[:200]}


result = {}


def call():
    t0 = time.time()
    result["res"] = req("/api/tools/call",
                        {"tool": "shell", "args": {"command": "sleep 120"},
                         "run_id": "canceltest"}, timeout=180)
    result["secs"] = round(time.time() - t0, 1)


th = threading.Thread(target=call)
th.start()

approved = None
for _ in range(40):
    time.sleep(0.5)
    pend = req("/api/approvals?status=pending", method="GET").get("approvals", [])
    rec = next((a for a in pend if a.get("run") == "canceltest"
                or a.get("tool") == "shell"), None)
    if rec:
        approved = req("/api/approvals/" + rec["id"],
                       {"decision": "approve", "by": "test"})
        break

time.sleep(1.5)
run = req("/api/tools/running", method="GET").get("running", [])
cancel = req("/api/tools/cancel", {"run_id": "canceltest"})
th.join(timeout=30)
res = result.get("res") or {}
inner = res.get("result") or {}
ok = (cancel.get("cancelled") is True and inner.get("cancelled") is True
      and result.get("secs", 999) < 20)

print("approved =", bool(approved))
print("running  =", run)
print("cancel   =", cancel)
print("call_secs=", result.get("secs"))
print("result   =", json.dumps(inner)[:400])
print("PASS" if ok else "FAIL")
