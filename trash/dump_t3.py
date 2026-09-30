#!/usr/bin/env python3
"""JAG-58 — dump T3 (fs.read) full event stream to see why no finish."""
import urllib.request
import urllib.parse

BASE = "http://127.0.0.1:8790"
H = {"Authorization": "Bearer REDACTED-COMPROMISED-TOKEN"}
g = urllib.parse.quote("Leggi il file README.md con il tool fs.read, poi chiama finish summary=ok")
req = urllib.request.Request(BASE + "/api/agent/run?goal=%s&max_steps=5" % g, headers=H)
cur = None
with urllib.request.urlopen(req, timeout=600) as r:
    for raw in r:
        line = raw.decode("utf-8", "replace").rstrip("\n")
        if line.startswith("event:"):
            cur = line.split(":", 1)[1].strip()
        elif line.startswith("data:") and cur in (
                "agent.thought", "agent.observation", "agent.finish",
                "agent.error", "tool.call", "tool.result", "agent.iteration"):
            print(cur, "->", line[5:][:300])
