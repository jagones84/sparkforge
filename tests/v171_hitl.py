"""v171 — HUMAN IN THE LOOP (JAG-171): with autocontinue OFF the harness must not
end on prose with open todos; it emits hitl.request and the visible reply is the
human gate. The autocontinue flag is read from runtime config.

Run:  python3 tests/v171_hitl.py
"""
import json
import os
import sys

REPO = "/home/jagones/Repositories/sparkforge"
os.chdir(REPO)
sys.path.insert(0, REPO)

import py_compile
py_compile.compile(os.path.join(REPO, "server.py"), doraise=True)

import server
import tools
import bestofn
import keepgoing

bestofn.n_of = lambda **k: 1
server.maybe_reflect = lambda *a, **k: None

# Force autocontinue OFF for this test (the harness must hand over to the human).
_orig = keepgoing.cfg
keepgoing.cfg = lambda override=None: {**_orig(override), "autocontinue": False}

# Model opens two todos then just writes prose WITHOUT closing them.
seq = [{"action": "write_todos", "todos": [{"label": "A"}, {"label": "B"}]},
       "Ho fatto il possibile, ma non posso proseguire."]
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

sess = server.get_or_create_session(None, title="v171")
if server.taskgraph.load(sess["id"]):
    server.taskgraph.reset(sess["id"])

events = []
server.chat_once(sess, "fai due passi", None, on_event=lambda k, **d: events.append((k, d)))

kinds = [k for k, _ in events]
hitls = [d for k, d in events if k == "hitl.request"]
assert "hitl.request" in kinds, "no HITL gate fired (autocontinue OFF)"
assert hitls and len(hitls[0].get("open") or []) >= 1, "HITL carried no open todos"

last = [m for m in sess.get("messages", []) if m.get("role") == "assistant"][-1]
assert "In pausa" in (last.get("content") or ""), "turn ended on prose, not the human gate"
assert last.get("hitl") is True, "assistant message not flagged as HITL"

g = server.taskgraph.load(sess["id"]) or {}
assert any(n.get("status") in ("todo", "doing", "blocked") for n in g.get("nodes", [])), \
    "expected open todos behind the gate"

# frontend wiring
html = open(os.path.join(REPO, "webui/index.html"), encoding="utf-8").read()
checks = {
    "hitl card": "function hitlCard(d)" in html,
    "hitl SSE listener": 'es.addEventListener("hitl.request"' in html,
    "HITL options + other + note": 'placeholder="Other: cosa devo fare?' in html and "hitl-note" in html,
    "autocontinue toggle": 'id="rtAuto"' in html,
    "autocontinue sent on save": "autocontinue: !!(($(\"rtAuto\")" in html,
}
bad = [k for k, ok in checks.items() if not ok]
for k, ok in checks.items():
    print(("PASS " if ok else "FAIL ") + k)
assert not bad, "frontend wiring missing: " + ", ".join(bad)

print("v171 OK: hitl open=%d | RESULT: PASS" % len(hitls[0].get("open") or []))
