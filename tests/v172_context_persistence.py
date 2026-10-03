"""v172 — the agentic history (tool calls, observations, nudges) must be PERSISTED
into sess["messages"] so the model retains its work across turns and the ctx
meter reflects the TRUE prompt (session test read 2% because only final replies
were stored). Internal entries must never leak to the provider, nor be
double-rendered in the UI.

Run:  python3 tests/v172_context_persistence.py
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

bestofn.n_of = lambda **k: 1
server.maybe_reflect = lambda *a, **k: None

# one tool call, then a prose answer.
seq = [{"action": "shell", "command": "echo hi"}, "Fatto: comando eseguito."]
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
    "ok": True, "tool": tool, "exit_code": 0, "stdout": "hi", "backend": "stub", "sandboxed": False}

sess = server.get_or_create_session(None, title="v172")
if server.taskgraph.load(sess["id"]):
    server.taskgraph.reset(sess["id"])
server.append_message(sess, "user", "esegui un comando e dimmi")  # like the /api/chat route

before = int((server.context_usage(sess["id"]) or {}).get("tokens_used") or 0)

server.chat_once(sess, "esegui un comando e dimmi", None, on_event=lambda k, **d: None)

msgs = sess.get("messages", [])
internal = [m for m in msgs if m.get("internal")]
visible = [m for m in msgs if not m.get("internal")]
print("messages total=%d internal=%d visible=%d" % (len(msgs), len(internal), len(visible)))
assert internal, "agentic history NOT persisted into messages"
roles = {m.get("role") for m in internal}
assert roles and roles <= {"user", "assistant"}, "unexpected internal roles: %s" % roles
obs = [m for m in internal if "Observation for tool" in str(m.get("content", ""))]
assert obs, "tool observation not persisted in the transcript"
print("internal roles:", sorted(roles), "| observation msgs:", len(obs))
assert visible and visible[-1].get("role") == "assistant" and not visible[-1].get("internal"), \
    "final assistant reply missing or flagged internal"

# the observation must actually reach the NEXT turn's prompt
nxt, _ = server.assemble_turn(sess, "e ora?", server._tool_context(), None, False)
blob = "\n".join(str(m.get("content", "")) for m in nxt)
assert "Observation for tool" in blob, "observation absent from the next-turn prompt"
print("next-turn prompt carries the observation: OK")

# ctx meter grows with the persisted work
after = int((server.context_usage(sess["id"]) or {}).get("tokens_used") or 0)
print("ctx tokens before=%d after=%d" % (before, after))
assert after > before, "ctx meter did not grow after persisting the agentic history"

# internal marker never leaks to the provider
body = server._completion_body("m", [{"role": "user", "content": "x", "internal": True}], False)
assert "internal" not in body["messages"][0], "internal marker leaked to the provider"
assert set(body["messages"][0].keys()) <= {"role", "content", "name"}, "unexpected wire keys"
print("wire keys:", sorted(body["messages"][0].keys()))

# UI must skip internal entries on reload (no duplicate bubbles)
html = open(os.path.join(REPO, "webui/index.html"), encoding="utf-8").read()
assert "if (m.internal) return;" in html, "UI does not skip internal history on reload"
print("frontend guard: OK")

# per-session isolation
s2 = server.get_or_create_session(None, title="v172-other")
assert len(s2.get("messages") or []) == 0, "fresh session inherited another session's messages"
print("isolation OK")

print("RESULT: ALL OK")
