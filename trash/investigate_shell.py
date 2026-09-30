#!/usr/bin/env python3
"""JAG-58 — why does shell produce no output? dump T5 + registry policy."""
import json
import urllib.request
import urllib.parse

BASE = "http://127.0.0.1:8790"
TOK = "REDACTED-COMPROMISED-TOKEN"
H = {"Authorization": "Bearer " + TOK}


KEEP = ("tool.call", "tool.result", "approval.", "agent.finish",
        "agent.observation", "tool.blocked", "agent.error")


def sse(path, timeout=600):
    req = urllib.request.Request(BASE + path, headers=H)
    cur = None
    with urllib.request.urlopen(req, timeout=timeout) as r:
        for raw in r:
            line = raw.decode("utf-8", "replace").rstrip("\n")
            if line.startswith("event:"):
                cur = line.split(":", 1)[1].strip()
            elif line.startswith("data:"):
                if cur and any(cur.startswith(k) for k in KEEP):
                    print(cur, "->", line[5:][:400])


print("=== T5 raw: shell goal ===")
g = urllib.parse.quote("Esegui il comando shell `echo JAG58`, verifica l'output, poi chiama finish summary=ok")
sse("/api/agent/run?goal=%s&max_steps=3" % g, timeout=400)

print("\n=== registry policy for shell / fs.read / skills / pmcp ===")
req = urllib.request.Request(BASE + "/api/tools", headers=H)
with urllib.request.urlopen(req, timeout=30) as r:
    d = json.loads(r.read().decode())
tools = d.get("tools") or d.get("catalog") or (d if isinstance(d, list) else [])
for t in tools:
    if isinstance(t, dict) and t.get("name") in ("shell", "fs.read", "fs.write", "skills", "pmcp__gateway.health"):
        print(f"  {t.get('name'):22s} enabled={t.get('enabled')} approval={t.get('approval')}")

print("\n=== pending approvals ===")
try:
    req = urllib.request.Request(BASE + "/api/approvals", headers=H)
    with urllib.request.urlopen(req, timeout=30) as r:
        print(r.read().decode()[:1500])
except Exception as e:
    print("err:", e)
