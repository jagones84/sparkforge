"""v176 — the harness COACHES a stuck model (JAG-178).

When a tool fails repeatedly (or the same call repeats), the harness injects a
socratic "YOU ARE STUCK" message that makes the model ask the RIGHT questions
(syntax? skill? another route? ask the user?) and reminds it that it has skills —
instead of the generic "Continue: call the next tool…".

Run:  python3 tests/v176_stuck_coach.py
"""
import json
import os
import sys

REPO = "/home/jagones/Repositories/sparkforge"
os.chdir(REPO)
sys.path.insert(0, os.path.join(REPO, "src"))

import py_compile
py_compile.compile(os.path.join(REPO, "src", "sparkforge", "server.py"), doraise=True)
print("[compile] server.py OK")

from sparkforge import server
from sparkforge import tools
from sparkforge import bestofn

server.maybe_reflect = lambda *a, **k: None
bestofn.n_of = lambda **k: 1

# every tool call fails with an adb syntax error
tools.execute = lambda tool, args, run_id=None: {
    "ok": False, "tool": tool, "exit_code": 1, "stdout": "",
    "stderr": "RuntimeError: adb: unknown command input", "backend": "stub",
    "sandboxed": False}

seq = [{"action": "shell", "command": "adb -s dev input tap 100 200"}] * 3 + ["Fermo e chiedo."]
calls = {"n": 0}


def fake_stream(messages, model, role, on_delta, timeout=300, usage=None, guard=None, cancel=None):
    a = seq[min(calls["n"], len(seq) - 1)]
    calls["n"] += 1
    ans = a if isinstance(a, str) else json.dumps(a)
    if on_delta:
        on_delta("answer", ans)
    return ans, "", (model or "stub")


server.stream_with_fallback = fake_stream

sess = server.get_or_create_session(None, title="v176")
if server.taskgraph.load(sess["id"]):
    server.taskgraph.reset(sess["id"])

events = []
server.chat_once(sess, "installa e verifica l'app", None,
                 on_event=lambda k, **d: events.append((k, d)))

texts = [(d.get("text") or "") for k, d in events
         if k == "harness.inject" and d.get("inject_kind") in ("observation", "coach")]
coach = [t for t in texts if "YOU ARE STUCK" in t]
print("injects:", len(texts), "| coach:", len(coach))
assert coach, "the harness never coached a stuck model"
c = coach[0]
for need in ("you are stuck", "failed", "skill", "syntax", "different route",
             "ask the user", "do not repeat"):
    assert need.lower() in c.lower(), "coach message missing %r" % need
print("coach head:", c.splitlines()[3][:90])

# the nudge names at least one real installed skill (keyword match on adb/android)
assert "e.g. " in c, "coach does not name any skill"

print("RESULT: ALL OK")
