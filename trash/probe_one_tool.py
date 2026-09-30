#!/usr/bin/env python3
"""Single raw tool call to inspect response shape."""
import json
import urllib.request

BASE = "http://127.0.0.1:8790"
TOKEN = "REDACTED-COMPROMISED-TOKEN"
HDR = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}

for tool in ["pmcp__time_get", "pmcp__echo", "pmcp__list", "skills"]:
    args = {"text": "hi"} if tool == "pmcp__echo" else {}
    if tool == "skills":
        args = {"action": "list"}
    body = json.dumps({"tool": tool, "args": args}).encode()
    r = urllib.request.Request(f"{BASE}/api/tools/call", data=body, headers=HDR, method="POST")
    with urllib.request.urlopen(r, timeout=60) as resp:
        d = json.loads(resp.read().decode())
    print(f"\n=== {tool} ({args}) ===")
    print(json.dumps(d, indent=2)[:1500])
