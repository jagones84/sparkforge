#!/usr/bin/env python3
import json
import sys

p = sys.argv[1] if len(sys.argv) > 1 else \
    "/home/jagones/Repositories/sparkforge/data/sessions/7ea956d4156c.json"
d = json.load(open(p, encoding="utf-8"))
msgs = d.get("messages", [])
print("session=%s  n_messages=%d" % (d.get("id"), len(msgs)))
for m in msgs[-4:]:
    c = m.get("content") or ""
    print("\n--- role=%s meta=%s len=%d ---" % (m.get("role"), m.get("meta"), len(c)))
    print(c[:1500])
