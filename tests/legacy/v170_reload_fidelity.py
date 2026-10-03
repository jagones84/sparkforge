"""v170 — a reload must be faithful: each persisted tool card carries the
chain-of-thought that led to it, plus its node, so the COTs between tools and
the nesting survive a refresh (JAG-170).

Run:  python3 tests/v170_reload_fidelity.py
"""
import json
import os
import sys

REPO = "/home/jagones/Repositories/sparkforge"
os.chdir(REPO)
sys.path.insert(0, os.path.join(REPO, "src"))

import py_compile
py_compile.compile(os.path.join(REPO, "src", "sparkforge", "server.py"), doraise=True)

from sparkforge import server
from sparkforge import tools
from sparkforge import bestofn

bestofn.n_of = lambda **k: 1
server.maybe_reflect = lambda *a, **k: None

seq = [{"action": "write_todos", "todos": [{"label": "step A"}]},
       {"action": "shell", "command": "true"},
       {"action": "shell", "command": "true"},
       {"action": "update_todos", "steps": [{"index": 0, "status": "done", "evidence": "e"}]},
       "fatto"]
calls = {"n": 0}


def fake_stream(messages, model, role, on_delta, timeout=300, usage=None, guard=None, cancel=None):
    a = seq[min(calls["n"], len(seq) - 1)]
    calls["n"] += 1
    ans = a if isinstance(a, str) else json.dumps(a)
    if on_delta:
        on_delta("think", "reasoning before step %d\n" % calls["n"])  # live CoT stream
        on_delta("answer", ans)
    return ans, "final think", (model or "stub")


server.stream_with_fallback = fake_stream
tools.execute = lambda tool, args, run_id=None: {
    "ok": True, "tool": tool, "exit_code": 0, "stdout": "ok", "backend": "stub", "sandboxed": False}

sess = server.get_or_create_session(None, title="v170")
if server.taskgraph.load(sess["id"]):
    server.taskgraph.reset(sess["id"])

server.chat_once(sess, "fai un passo con due tool", None, on_event=lambda k, **d: None)

cards = sess.get("tool_cards") or []
assert cards, "no tool cards persisted"
assert all("node" in c for c in cards), "card lacks 'node' -> cannot nest on reload"
assert any(c.get("think") for c in cards), "card lacks 'think' -> CoTs between tools lost on reload"
assert sess.get("injects"), "no injects persisted -> harness feed lost on reload"

# frontend wiring for the faithful reload
html = open(os.path.join(REPO, "webui/index.html"), encoding="utf-8").read()
checks = {
    "per-card CoT render": "function renderThink(text)" in html,
    "chronological lazy node": "const ensureNode = (nid) =>" in html,
    "card think rendered": "if (v.think) renderThink(v.think);" in html,
    "active node still shown (JAG-176: no wall of empty bars)":
        'const _activeNode = nodes.find(n => n.status === "doing" || n.status === "blocked");' in html,
    "stable indentation": "if (n && n.parent && n.parent !== id) return _nodeDepth" in html,
}
bad = [k for k, ok in checks.items() if not ok]
for k, ok in checks.items():
    print(("PASS " if ok else "FAIL ") + k)
assert not bad, "frontend wiring missing: " + ", ".join(bad)

print("v170 OK: cards %d, with think %d | RESULT: PASS"
      % (len(cards), sum(1 for c in cards if c.get("think"))))
