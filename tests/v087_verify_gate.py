#!/usr/bin/env python3
"""JAG-87 — verification gate: a turn must not end with OPEN plan steps.

Mirrors the v077 stubbing style: the model is faked, the loop is real.
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
os.environ.setdefault("SPARKFORGE_DB", os.path.join(REPO, "data", "events.db"))

import server      # noqa: E402
import taskgraph   # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(ok)
    print(("PASS " if ok else "FAIL ") + name + ((" — " + detail) if detail else ""))


def _txt(r):
    """chat_once returns the reply dict; tolerate a plain string too."""
    if isinstance(r, dict):
        return r.get("content") or ""
    return r or ""


calls = {"n": 0}


def fake_stream(msgs, model, kind, on_delta, timeout=300, usage=None):
    calls["n"] += 1
    return seq.pop(0) if seq else ("Fine.", "", model)


server.stream_with_fallback = fake_stream
server.api_v02.gated_call = lambda tool, args, run_id=None, timeout=None: {
    "status": "executed", "observation": "ok"}

# ---------- A: an OPEN plan must trigger the gate ----------
sid = "jag87-gate-test"
taskgraph.reset(sid)
seq = [
    ('{"action":"write_todos","todos":[{"label":"passo uno","deps":[],"parent":null},'
     '{"label":"passo due","deps":[],"parent":null}]}', "", "m"),
    ("Fatto: completato tutto.", "", "m"),                       # must be GATED
    ("Ho verificato: passo uno e passo due completati; prove: ...", "", "m"),
]
sess = server.get_or_create_session(sid)
reply, _ = server.chat_once(sess, "fai due cose", None)
content = _txt(reply)
c = taskgraph.counts(taskgraph.load(sid))
check("A1 the gate forced an extra model call", calls["n"] >= 3, "calls=%d" % calls["n"])
check("A2 the gated premature answer never reached the user",
      "Fatto: completato tutto." not in content, repr(content[:70]))
check("A3 the post-gate real answer is what shipped",
      "verificato" in content.lower(), repr(content[:90]))
check("A4 the harness did NOT fake-close the open steps",
      (c.get("todo", 0) + c.get("doing", 0)) >= 1, "counts=%s" % c)

# ---------- B: no plan -> no gate ----------
sid2 = "jag87-nogate-test"
taskgraph.reset(sid2)
seq = [("Ecco la risposta finale, nessun piano necessario.", "", "m")]
calls["n"] = 0
sess2 = server.get_or_create_session(sid2)
reply2, _ = server.chat_once(sess2, "ciao, dimmi una cosa", None)
check("B1 no plan -> no gate (single final call)", calls["n"] == 1, "calls=%d" % calls["n"])
check("B2 the answer shipped", "risposta finale" in _txt(reply2), repr(_txt(reply2)[:60]))

fails = [r for r in results if not r]
print("\n=== %d/%d checks passed ===" % (len(results) - len(fails), len(results)))
sys.exit(1 if fails else 0)
