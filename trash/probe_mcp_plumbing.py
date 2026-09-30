#!/usr/bin/env python3
"""Probe MCP plumbing via auto-approved pmcp__gateway.* tools."""
import json
import urllib.request

BASE = "http://127.0.0.1:8790"
TOKEN = "REDACTED-COMPROMISED-TOKEN"
HDR = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}


def call(body, timeout=60):
    r = urllib.request.Request(f"{BASE}/api/tools/call",
                                data=json.dumps(body).encode(),
                                headers=HDR, method="POST")
    with urllib.request.urlopen(r, timeout=timeout) as resp:
        return resp.status, json.loads(resp.read().decode())


for tool, args in [
    ("pmcp__gateway.health", {}),
    ("pmcp__gateway.config_status", {}),
    ("pmcp__gateway.tasks_list", {}),
]:
    s, d = call({"tool": tool, "args": args}, timeout=60)
    res = (d or {}).get("result") or {}
    print(f"\n=== {tool} ===")
    print(f"  top status={d.get('status') if isinstance(d, dict) else 'n/a'}")
    print(f"  result.ok={res.get('ok')}")
    print(f"  stdout={(res.get('stdout') or '')[:400]!r}")
    print(f"  stderr={(res.get('stderr') or '')[:200]}")
