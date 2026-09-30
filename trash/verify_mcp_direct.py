#!/usr/bin/env python3
"""JAG-57 v4 — test the MCP plumbing directly + final report."""
import json
import urllib.request

BASE = "http://127.0.0.1:8790"
TOKEN = "REDACTED-COMPROMISED-TOKEN"
HDR = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}


def get(p):
    r = urllib.request.Request(f"{BASE}{p}", headers=HDR)
    with urllib.request.urlopen(r, timeout=30) as resp:
        return resp.status, json.loads(resp.read().decode())


def post(p, body, timeout=300):
    r = urllib.request.Request(f"{BASE}{p}", data=json.dumps(body).encode(),
                                headers=HDR, method="POST")
    with urllib.request.urlopen(r, timeout=timeout) as resp:
        return resp.status, json.loads(resp.read().decode())


print("=== Direct tool execution: pmcp__* (one of the 26 tools) ===")
# pick a safe tool — pmcp__time_get or pmcp__echo
for try_name, args in [
    ("pmcp__time_get", {}),
    ("pmcp__echo", {"text": "hello"}),
]:
    s, d = post("/api/tools/call", {"tool": try_name, "args": args}, timeout=60)
    res = (d or {}).get("result") or d
    print(f"\n{try_name}: status={s} ok={res.get('ok')}")
    print(f"  stdout_head={(res.get('stdout') or '')[:300]!r}")
    print(f"  stderr={(res.get('stderr') or '')[:200]}")

print("\n=== /api/mcp/clients final state ===")
s, d = get("/api/mcp/clients")
print(json.dumps(d, indent=2))

print("\n=== Plan/tasks summary ===")
s, d = get("/api/plan")
print(f"plan={json.dumps(d, indent=2)[:500]}")
s, d = get("/api/tasks")
print(f"tasks={json.dumps(d, indent=2)[:500]}")
