#!/usr/bin/env python3
"""Probe: which model is in use, and what does the router expose?"""
import json
import urllib.request

BASE = "http://127.0.0.1:8790"
TOKEN = "REDACTED-COMPROMISED-TOKEN"
HDR = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}


def get(p):
    r = urllib.request.Request(f"{BASE}{p}", headers=HDR)
    with urllib.request.urlopen(r, timeout=30) as resp:
        return resp.status, json.loads(resp.read().decode())


print("=== /api/selfcheck ===")
s, d = get("/api/selfcheck")
print(json.dumps(d, indent=2))

print("\n=== /api/models ===")
s, d = get("/api/models")
print(json.dumps(d, indent=2)[:1500])

print("\n=== /api/routing ===")
try:
    s, d = get("/api/routing")
    print(json.dumps(d, indent=2)[:1500])
except Exception as e:
    print(f"err: {e}")

print("\n=== /api/runs (last 5) ===")
s, d = get("/api/runs?limit=5")
print(json.dumps(d, indent=2)[:1500])
