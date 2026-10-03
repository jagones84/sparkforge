"""v174 — 100% per-session independence + clarity.

Switching/leaving a session must never touch another session's stuff:
  - the message QUEUE is keyed by session (never flushed into another session);
  - /api/feed events are filtered by session (approval.request carries `run`=session);
  - the harness owns the plan and the messages say so, with an explicit
    "never redo a step already marked [x]" rule;
  - identical consecutive harness injects are collapsed in the UI.

Run:  python3 tests/v174_session_isolation.py
"""
import os
import sys

REPO = "/home/jagones/Repositories/sparkforge"
os.chdir(REPO)
sys.path.insert(0, REPO)

import py_compile
py_compile.compile(os.path.join(REPO, "server.py"), doraise=True)
py_compile.compile(os.path.join(REPO, "taskgraph.py"), doraise=True)
print("[compile] server.py + taskgraph.py OK")

from taskgraph import render_todos

txt = render_todos({"nodes": [{"id": "n1", "label": "x", "status": "todo"}]})
assert "This list is YOURS" in txt, "render_todos lost the model-owns-it contract"
assert "NEVER redo a step already marked [x]" in txt, "no anti-redo rule in the task list"
print("render_todos: contract + anti-redo OK")

srv = open(os.path.join(REPO, "server.py"), encoding="utf-8").read()
assert "it is YOURS to keep current" in srv, "the write_todos nudge is not clear about ownership"
assert "Never redo a step already" in srv, "no anti-redo rule in the nudge"
assert "an abort can cut the model mid tool-call" in srv, "abort path does not guard raw tool-call JSON"
print("write_todos / update_todos nudges + abort guard: OK")

html = open(os.path.join(REPO, "webui/index.html"), encoding="utf-8").read()
checks = {
    "queue keyed by session": "let msgQueue = {};" in html and "function _q(sid)" in html,
    "flush never crosses sessions": "if (sessionId !== s || turnSSE[s]) return;" in html,
    "selectSession re-renders its queue": "renderQueue();   // JAG-174" in html,
    "approval filtered by session/run": "const _s = d.session || d.run;" in html,
    "improve.proposal filtered": 'if (!d.session || d.session === sessionId) improveCard(d);' in html,
    "improve.nudge filtered": "if (d.session && d.session !== sessionId) return;" in html,
    "inject dedupe counter": 'class="hcount"' in html and "prev.dataset.k === key" in html,
    "no abort on switch": html.count('"/api/chat/abort"') == 1,
}
bad = [k for k, ok in checks.items() if not ok]
for k, ok in checks.items():
    print(("PASS " if ok else "FAIL ") + k)
assert not bad, "session-isolation checks missing: " + ", ".join(bad)

print("RESULT: ALL OK")
