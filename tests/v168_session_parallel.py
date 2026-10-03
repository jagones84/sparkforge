"""v168 — the WebUI must keep each chat turn bound to ITS session, and "stop"
must abort the turn SERVER-side. Static regression guard (JAG-168).

Run:  python3 tests/v168_session_parallel.py
"""
import os

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
html = open(os.path.join(REPO, "webui/index.html"), encoding="utf-8").read()

checks = {
    "per-session SSE registry": "let turnSSE = {}" in html,
    "per-session running set": "let runningSessions = {}" in html,
    "render only when the session is on screen":
        "const live = () => !!turnSession && turnSession === sessionId" in html,
    "global feed never paints another session's node":
        "if (d.session && d.session !== sessionId) return;" in html,
    "sidebar busy marker": 'classList.toggle("running"' in html,
    "queue/flush gated per session":
        "if (turnSSE[sessionId] || !msgQueue.length) return;" in html,
    "stop aborts the server turn": '"/api/chat/abort"' in html and "session: sessionId" in html,
}
bad = [k for k, ok in checks.items() if not ok]
for k, ok in checks.items():
    print(("PASS " if ok else "FAIL ") + k)
print("RESULT:", "PASS" if not bad else ("FAIL " + ", ".join(bad)))
raise SystemExit(1 if bad else 0)
