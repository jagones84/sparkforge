"""v173 — the TODO LIST belongs to the MODEL (standard contract, a la Claude Code
TodoWrite): the agent marks a step 'doing' then 'done' with evidence. The harness
ENFORCES and REMINDS but NEVER auto-closes a step (closing a step that is not
truly done is "lying about completion"). Also: clear injected messages + a
"never redo a done step" rule.

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
tools.execute = lambda tool, args, run_id=None: {
    "ok": True, "tool": tool, "exit_code": 0, "stdout": "ok", "backend": "stub", "sandboxed": False}


def run_turn(title, seq):
    calls = {"n": 0}

    def fake_stream(messages, model, role, on_delta, timeout=300, usage=None, guard=None, cancel=None):
        a = seq[min(calls["n"], len(seq) - 1)]
        calls["n"] += 1
        ans = a if isinstance(a, str) else json.dumps(a)
        if on_delta:
            on_delta("answer", ans)
        return ans, "", (model or "stub")

    server.stream_with_fallback = fake_stream
    sess = server.get_or_create_session(None, title=title)
    if server.taskgraph.load(sess["id"]):
        server.taskgraph.reset(sess["id"])
    events = []
    server.chat_once(sess, "go", None, on_event=lambda k, **d: events.append((k, d)))
    return sess, events


# A) the model does the work and reports in prose, but NEVER marks anything done
#    -> the harness must NOT close the steps itself.
sess, events = run_turn("v173a", [
    {"action": "write_todos", "todos": [{"label": "A"}, {"label": "B"}]},
    {"action": "shell", "command": "true"}, "Passo A fatto.",
    {"action": "shell", "command": "true"}, "Passo B fatto.",
    {"action": "shell", "command": "true"}, "Ho finito."])
nodes = (server.taskgraph.load(sess["id"]) or {}).get("nodes", [])
print("A nodes:", [(n["label"], n["status"], n.get("source")) for n in nodes])
assert not any(k == "plan.autoclosed" for k, _ in events), \
    "the harness AUTO-CLOSED a step — non-standard and unsafe"
assert not any(str(n.get("source", "")).startswith("harness") for n in nodes), \
    "the harness mutated the plan (source harness:*)"
assert all(n["status"] != "done" for n in nodes), \
    "a step was marked done without the model providing evidence"
assert any(n["status"] in ("todo", "doing", "blocked") for n in nodes), \
    "no open step left after a turn that closed nothing"
inj = "\n".join((d.get("text") or "") for k, d in events
                if k == "harness.inject" and d.get("inject_kind") == "continue")
assert "update_todos" in inj and "YOUR" in inj, "continue message is not clear about the contract"
print("A: no auto-close + clear contract OK")

# B) the MODEL closes a step with evidence -> it is persisted (model-driven)
sess2, _ = run_turn("v173b", [
    {"action": "write_todos", "todos": [{"label": "C"}]},
    {"action": "shell", "command": "true"},
    {"action": "update_todos", "steps": [{"index": 0, "status": "done", "evidence": "ran true, exit 0"}]},
    "Fatto."])
nodes2 = (server.taskgraph.load(sess2["id"]) or {}).get("nodes", [])
print("B nodes:", [(n["label"], n["status"], n.get("source")) for n in nodes2])
assert nodes2 and nodes2[0]["status"] == "done", "the model's update_todos did not close the step"
assert nodes2[0].get("source") == "model:update_todos", "step closed by the wrong actor"
assert nodes2[0].get("evidence"), "step closed without evidence"
print("B: model-driven close with evidence OK")

# C) the persistent list states the contract + the anti-redo rule
from taskgraph import render_todos
txt = render_todos({"nodes": [{"id": "n1", "label": "x", "status": "todo"}]})
assert "NEVER redo a step already marked [x]" in txt, "no anti-redo rule in the task list"
assert "YOURS" in txt, "the task list does not state that the model owns it"
print("C: render_todos contract OK")

print("RESULT: ALL OK")
