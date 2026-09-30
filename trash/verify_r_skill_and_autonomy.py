#!/usr/bin/env python3
"""JAG-58 — read skill `r`, dump MCP config, verify LLM autonomy still broken."""
import json
import urllib.request
import subprocess

BASE = "http://127.0.0.1:8790"
TOKEN = "REDACTED-COMPROMISED-TOKEN"
HDR = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}


def call(body, timeout=120):
    r = urllib.request.Request(f"{BASE}/api/tools/call", data=json.dumps(body).encode(),
                                headers=HDR, method="POST")
    with urllib.request.urlopen(r, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def get(p, timeout=30):
    r = urllib.request.Request(f"{BASE}{p}", headers=HDR)
    with urllib.request.urlopen(r, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


print("=== STEP 1: read skill `r` via skills tool ===")
d = call({"tool": "skills", "args": {"action": "read", "name": "r"}})
res = d.get("result") or {}
body = res.get("stdout", "") or ""
print(f"ok={res.get('ok')} bytes={len(body)}")
print("--- content ---")
print(body[:2500])
print("--- end ---")

print("\n=== STEP 2: config/mcp_clients.yaml ===")
out = subprocess.run(
    ["ssh", "dgx", "cat /home/jagones/Repositories/sparkforge/config/mcp_clients.yaml 2>/dev/null"],
    capture_output=True, text=True, timeout=20)
print(out.stdout)

print("\n=== STEP 3: list all loaded MCP clients ===")
mc = get("/api/mcp/clients")
print(json.dumps(mc, indent=2)[:1500])

print("\n=== STEP 4: is `r` MCP exposed? probe r__* tool names ===")
for tn in ["r__echo", "r__run", "r__evaluate", "r__script", "pmcp__r.echo"]:
    d = call({"tool": tn, "args": {}}, timeout=30)
    res = d.get("result") or {}
    print(f"  {tn}: ok={res.get('ok')} err={(res.get('stderr','') or '')[:120]}")

print("\n=== STEP 5: minimal autonomy re-check ===")
d2 = call({"tool": "self", "args": {}}, timeout=30)
self_res = d2.get("result") or {}
print(f"self.ok={self_res.get('ok')}")
print(f"router: {(self_res.get('router') or '')[:200]}")

print("\n=== STEP 6: agent run (5 max_steps) — same loop bug? ===")
r2 = urllib.request.Request(f"{BASE}/api/agent/run",
    data=json.dumps({"goal": "Call skills read name=paperclip then action=finish.", "max_steps": 4}).encode(),
    headers=HDR, method="POST")
with urllib.request.urlopen(r2, timeout=300) as resp:
    ad = json.loads(resp.read().decode())
trace = ad.get("trace") or []
called = [t.get("tool") for t in trace if t.get("tool")]
unique = set(called)
print(f"status={ad.get('status')} summary={(ad.get('summary','') or '')[:120]}")
print(f"trace_items={len(trace)} tools_called={called} unique={unique}")
print(f"finished_clean={ad.get('status') == 'done'}")
