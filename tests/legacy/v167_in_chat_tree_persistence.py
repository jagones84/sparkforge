"""v167 — regression: the agent must NOT stop, and the in-chat tree must persist.

Covers the two guarantees asked for after JAG-164/166/167:
  1. a turn that spends more than one tool budget keeps going (keepgoing refill),
     closes every todo, and surfaces every harness injection in the chat;
  2. cards / injections / replies are persisted WITH their node, are attributable
     on reload, and never leak harness metadata to the provider.

Run:  python3 tests/v167_in_chat_tree_persistence.py
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

bestofn.n_of = lambda **k: 1
server.maybe_reflect = lambda *a, **k: None

# A turn that (a) opens two todos, (b) spends MORE than one tool budget so the
# continuation loop must kick in (proving the agent does NOT stop), then closes
# every todo.
seq = [{"action": "write_todos", "todos": [{"label": "step A"}, {"label": "step B"}]}]
seq += [{"action": "shell", "command": "true"} for _ in range(10)]
seq += [{"action": "update_todos", "steps": [
    {"index": 0, "status": "done", "evidence": "e0"},
    {"index": 1, "status": "done", "evidence": "e1"}]}]
seq += ["Fatto: entrambi i passi completati."]

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

sess = server.get_or_create_session(None, title="v167-test")
if server.taskgraph.load(sess["id"]):
    server.taskgraph.reset(sess["id"])

events = []
server.chat_once(sess, "fai due passi lunghi", None,
                 on_event=lambda k, **d: events.append((k, d)))

# --- 1. the agent does not stop: every todo closed, continuation fired --------
injects = [(d.get("inject_kind"), (d.get("text") or "")[:40]) for k, d in events if k == "harness.inject"]
kinds = [k for k, _ in injects]
cont = sum(1 for k, _ in events if k == "plan.continuing")
g = server.taskgraph.load(sess["id"]) or {}
nodes = [(n.get("label"), n.get("status")) for n in g.get("nodes", [])]
print("harness.inject kinds:", kinds)
print("plan.continuing:", cont)
print("nodes:", nodes)

assert "system" in kinds, "system prompt not surfaced in chat"
assert any(k != "system" for k in kinds), "no synthetic injection surfaced in chat"
assert cont >= 1, "continuation loop never fired -> agent would have stopped"
assert nodes and all(s == "done" for _, s in nodes), "todos left open (agent stopped)"

# --- 2. injections persisted (visible after reload), system skipped -----------
inj = sess.get("injects") or []
print("persisted injects:", len(inj), "kinds:", sorted({r.get("kind") for r in inj}))
assert inj, "no inject persisted -> reload would lose the harness feed"
assert all(r.get("kind") != "system" for r in inj), "transient system prompt was persisted"
assert all("text" in r and "after" in r and "node" in r for r in inj), "inject record incomplete"

# --- 3. tool cards persisted AND nested under a node --------------------------
cards = sess.get("tool_cards") or []
print("persisted cards:", len(cards), "nodes:", sorted({c.get("node") for c in cards}))
assert len(cards) >= 10, "tool cards not persisted"
assert any(c.get("node") for c in cards), "no tool card nested under a todo node"

# --- 4. the final assistant reply is attributable to a node -------------------
last = [m for m in sess.get("messages", []) if m.get("role") == "assistant"][-1]
assert "node" in last, "assistant message carries no node -> cannot nest on reload"
print("final assistant node:", last.get("node"))

# --- 5. harness metadata never leaks to the provider --------------------------
body = server._completion_body("m", [{"role": "assistant", "content": "x", "node": "n1"}], False)
assert "node" not in body["messages"][0], "node metadata leaked to the provider request"
assert set(body["messages"][0].keys()) <= {"role", "content", "name"}, "unexpected wire keys"
print("wire keys:", sorted(body["messages"][0].keys()))

# --- 6. per-session isolation -------------------------------------------------
s2 = server.get_or_create_session(None, title="v167-other")
assert len((server.taskgraph.load(s2["id"]) or {}).get("nodes", [])) == 0, "fresh session has foreign todos"
assert not (s2.get("injects") or []), "fresh session inherited another session's injects"
print("isolation OK")

print("RESULT: ALL OK")
