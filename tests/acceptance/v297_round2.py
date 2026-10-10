#!/usr/bin/env python3
"""v297 — round-2 bug fixes (JAG-299).

Locked here:
  * server.py: a chat turn only clears ITS OWN `_ACTIVE_CHAT` registration (a
    token), so two overlapping requests on one session no longer have the first
    turn's exit mark the second as inactive (broke /api/chat/live + attach);
  * console.html: `endTurn` clears the demo typing interval, so Abort in demo mode
    actually stops the fake streaming;
  * editor.js: read/write/raw are scoped to the session workspace (the tree always
    was; these calls were not).

Deterministic, no live model. Run: python3 tests/v297_round2.py
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "src"))
sys.path.insert(0, os.path.join(REPO, "src"))

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


def read(*parts):
    with open(os.path.join(REPO, *parts), encoding="utf-8") as f:
        return f.read()


# ---------------------------------------------------------------- server.py
s = read("src", "longrun", "core/server.py") + read("src", "longrun", "core/httpapi.py")
check("turn registration carries a unique token", '"tok": _turn_tok' in s)
check("only the owning turn clears its registration",
      'if (_ACTIVE_CHAT.get(sess["id"]) or {}).get("tok") is _turn_tok:' in s)
check("exactly one _ACTIVE_CHAT pop remains (the guarded one)",
      s.count("_ACTIVE_CHAT.pop(sess[\"id\"], None)") == 1)

# -------------------------------------------------------------- console.html
c = read("webui", "console.html")
check("endTurn clears the demo typing interval",
      "if (demoTyping){ clearInterval(demoTyping); demoTyping = null; }" in c)

# ---------------------------------------------------------------- editor.js
e = read("webui", "assets", "editor.js")
check("editor fs calls are session-scoped", e.count("sessionQS()") >= 3)
check("editor write passes the session", "content: t.value, session: SESSION()" in e)
check("editor read/raw use sessionQS",
      "jget(\"/api/fs/read?path=\" + encodeURIComponent(path) + sessionQS())" in e
      and "/api/fs/raw?path=\" + encodeURIComponent(t.path)" in e)

print("---")
passed = sum(results)
print("%d/%d PASS" % (passed, len(results)))
sys.exit(0 if passed == len(results) else 1)

