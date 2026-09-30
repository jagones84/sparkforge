#!/usr/bin/env python3
"""JAG-58b — dump the chat reply to see if the model tries a tool or ignores it."""
import json
import urllib.request

BASE = "http://127.0.0.1:8790"
H = {"Authorization": "Bearer REDACTED-COMPROMISED-TOKEN",
     "Content-Type": "application/json"}
body = json.dumps({"message":
    "Usa il tool skills con action=list e dimmi quante skill ci sono. Poi rispondi."}).encode()
req = urllib.request.Request(BASE + "/api/chat/stream", data=body, headers=H, method="POST")
cur = None
answer = []
with urllib.request.urlopen(req, timeout=400) as r:
    for raw in r:
        line = raw.decode("utf-8", "replace").rstrip("\n")
        if line.startswith("event:"):
            cur = line.split(":", 1)[1].strip()
        elif line.startswith("data:"):
            if cur in ("tool.call", "tool.result", "chat.run"):
                print(cur, "->", line[5:][:300])
            elif cur == "chat.delta":
                d = json.loads(line[5:])
                if d.get("channel") == "answer":
                    answer.append(d.get("text", ""))
print("\n--- final ANSWER (channel=answer) ---")
print("".join(answer)[:1500])
