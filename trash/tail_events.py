#!/usr/bin/env python3
import json
import urllib.request

TOK = "REDACTED-COMPROMISED-TOKEN"


def get(path):
    r = urllib.request.Request("http://127.0.0.1:8790" + path,
                               headers={"Authorization": "Bearer " + TOK})
    return json.loads(urllib.request.urlopen(r, timeout=8).read())


for p in ("/api/feed?limit=120", "/api/events?limit=120", "/api/events?since=0&limit=120"):
    try:
        d = get(p)
        evs = d.get("events") if isinstance(d, dict) else d
        print("ENDPOINT OK:", p, "n=", len(evs or []))
        break
    except Exception as e:
        print("fail", p, e)
else:
    raise SystemExit(0)

keep = ("chat.run", "chat.done", "chat.error", "context.built", "graph.",
        "tool.call", "tool.result", "approval.", "agent.")
for e in (evs or [])[-60:]:
    k = e.get("kind") or e.get("event") or e.get("type")
    if not k or not any(k.startswith(x) for x in keep):
        continue
    d = e.get("data") or {}
    s = json.dumps(d, ensure_ascii=False)
    print("%-18s %s" % (k, s[:180]))
