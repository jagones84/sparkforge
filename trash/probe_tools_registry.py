#!/usr/bin/env python3
"""Probe tool registry: what is actually exposed + any pmcp__* tool names?"""
import json
import urllib.request

BASE = "http://127.0.0.1:8790"
TOKEN = "REDACTED-COMPROMISED-TOKEN"
HDR = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}


def get(p):
    r = urllib.request.Request(f"{BASE}{p}", headers=HDR)
    with urllib.request.urlopen(r, timeout=30) as resp:
        return resp.status, json.loads(resp.read().decode())


print("=== /api/tools ===")
s, d = get("/api/tools")
print(f"type={type(d).__name__}")
if isinstance(d, dict):
    print("keys=", list(d.keys()))
    tools = d.get("tools") or d.get("catalog") or []
    print(f"tools_count={len(tools)}")
    for t in tools[:60]:
        if isinstance(t, dict):
            print(f"  - {t.get('name')} enabled={t.get('enabled')} approval={t.get('approval')}")
        else:
            print(f"  - {t}")
elif isinstance(d, list):
    print(f"list_len={len(d)}")
    for t in d[:60]:
        print(f"  - {t}")
else:
    print(repr(d)[:300])

print("\n=== count pmcp__* tools ===")
text = json.dumps(d)
print(f"contains_pmcp__={text.count('pmcp__')}")
