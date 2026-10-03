"""v173 — the HARNESS owns the plan bookkeeping.

The model must never be asked to call `update_todos`: when it delivers a step in
plain prose the SYSTEM marks that step done for it (evidence = the answer), and
the injected messages say so clearly. Also checks the reply-density CSS and the
per-session CoT reset.

Run:  python3 tests/v173_harness_owns_plan.py
"""
import json
import os
import sys

REPO = "/home/jagones/Repositories/sparkforge"
os.chdir(REPO)
sys.path.insert(0, REPO)

import py_compile
py_compile.compile(os.path.join(REPO, "server.py"), doraise=True)
print("[compile] server.py OK")

import server
import tools
import bestofn

server.maybe_reflect = lambda *a, **k: None
bestofn.n_of = lambda **k: 1

# The model writes 2 todos, DOES the work (a shell per step) and only ever
# reports in PROSE — it never calls update_todos.
seq = [{"action": "write_todos", "todos": [{"label": "A"}, {"label": "B"}]},
       {"action": "shell", "command": "true"}, "Passo A fatto.",
       {"action": "shell", "command": "true"}, "Passo B fatto.",
       {"action": "shell", "command": "true"}, "Tutto fatto."]
calls = {"n": 0}


def fake_stream(messages, model, role, on_delta, timeout=300, usage=None, guard=None, cancel=None):
    a = seq[min(calls["n"], len(seq) - 1)]
    calls["n"] += 1
    ans = a if isinstance(a, str) else json.dumps(a)
    if on_delta:
        on_delta("answer", ans)
    return ans, "", (model or "stub")


server.stream_with_fallback = fake_stream
tools.execute = lambda tool, args, run_id=None: {
    "ok": True, "tool": tool, "exit_code": 0, "stdout": "ok", "backend": "stub", "sandboxed": False}

sess = server.get_or_create_session(None, title="v173")
if server.taskgraph.load(sess["id"]):
    server.taskgraph.reset(sess["id"])

events = []
server.chat_once(sess, "fai due passi", None, on_event=lambda k, **d: events.append((k, d)))

g = server.taskgraph.load(sess["id"]) or {}
nodes = g.get("nodes", [])
print("nodes:", [(n.get("label"), n.get("status"), n.get("source")) for n in nodes])

# 1. the SYSTEM closed the steps (no update_todos was ever emitted)
auto = [n for n in nodes if n.get("source") == "harness:autoclose"]
assert auto, "harness never auto-closed a step the agent delivered"
assert nodes and all(n.get("status") == "done" for n in nodes), \
    "steps left open even though the agent delivered them"
assert not any("update_todos" in json.dumps(d) for k, d in events if k == "tool.call"), \
    "the model was expected to do bookkeeping (update_todos was exercised)"
print("auto-closed:", [n.get("label") for n in auto])

# 2. clear system messages state the harness owns the plan
injs = [d for k, d in events if k == "harness.inject" and d.get("inject_kind") == "continue"]
blob = "\n".join(d.get("text") or "" for d in injs)
assert injs and "bookkeeping is MINE" in blob, "no clear 'bookkeeping is mine' inject"
assert "update_todos" in blob, "the inject does not tell the model to skip update_todos"
print("continue injects:", len(injs))

# 3. the persistent list itself tells the model the harness marks steps
from taskgraph import render_todos
txt = render_todos({"nodes": [{"id": "n1", "label": "x", "status": "todo"}]})
assert "HARNESS" in txt and "update_todos" in txt, "render_todos does not state the contract"
print("render_todos contract: OK")

# 4. frontend: reply density + per-session CoT reset
html = open(os.path.join(REPO, "webui/index.html"), encoding="utf-8").read()
checks = {
    "bubble dense font": "font-size: 12.5px; line-height: 1.5;" in html,
    "loose-list gap killed": ".bubble.md-content li > p { margin: 0; }" in html,
    "tight paragraph margin": ".bubble.md-content p { margin: 0 0 4px; }" in html,
    "CoT drawer reset on switch": "never carry\n  // another session's chain-of-thought" in html,
}
bad = [k for k, ok in checks.items() if not ok]
for k, ok in checks.items():
    print(("PASS " if ok else "FAIL ") + k)
assert not bad, "frontend checks missing: " + ", ".join(bad)

print("RESULT: ALL OK")
