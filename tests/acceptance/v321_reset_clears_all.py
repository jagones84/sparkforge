#!/usr/bin/env python3
"""v321 — "reset" must TRULY clear the chat, not only the message list (JAG-321).

Reported by the user: the reset buttons do not clear the chat completely. Root
cause: the transcript the WebUI rebuilds on reload (`loadHistory`) is the merge of
three persisted stores — `messages` + `tool_cards` + `injects` — but the
`POST /api/sessions/<id>/clear` endpoint wiped only `messages`, so the tool cards
and the harness entries (nudge / pivot / final / retry) reappeared immediately.
Both UIs (the composer "reset" in index.html and the agent "reset" in
orbit.html) call that one endpoint.

Deterministic, no model. Run: python3 tests/acceptance/v321_reset_clears_all.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-321-")
os.environ["SPARKFORGE_SESSIONS_DIR"] = os.path.join(TMP, "sessions")
os.environ["SPARKFORGE_GRAPH_DIR"] = os.path.join(TMP, "graphs")
os.environ["SPARKFORGE_DB"] = os.path.join(TMP, "events.db")
os.makedirs(os.environ["SPARKFORGE_SESSIONS_DIR"], exist_ok=True)
os.makedirs(os.environ["SPARKFORGE_GRAPH_DIR"], exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from sparkforge import server, taskgraph  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


SID = "v321clean"
sess = server.get_or_create_session(SID, "reset me")
sess.setdefault("messages", []).extend([
    {"role": "user", "content": "hello", "ts": 1.0},
    {"role": "assistant", "content": "hi", "ts": 2.0},
])
sess.setdefault("tool_cards", []).append(
    {"tool": "update_todos", "ts": 3.0, "after": 2, "result": "x"})
sess.setdefault("injects", []).append(
    {"kind": "nudge", "text": "do it", "ts": 4.0, "after": 2})
server.save_session(sess)
g = taskgraph.ensure(SID, session_id=SID, goal="x")
taskgraph.add_node(g, "a step")

pre = server.load_session(SID)
check("A0 the session has all three transcript stores to clear",
      bool(pre.get("messages")) and bool(pre.get("tool_cards")) and bool(pre.get("injects")),
      "messages=%d cards=%d injects=%d" % (len(pre.get("messages") or []),
                                           len(pre.get("tool_cards") or []),
                                           len(pre.get("injects") or [])))

out = server.clear_session(SID)
check("A1 clear_session returns the (kept) session",
      isinstance(out, dict) and out.get("id") == SID)

post = server.load_session(SID)
check("B1 messages wiped", post.get("messages") == [], str(post.get("messages")))
check("B2 tool_cards wiped", post.get("tool_cards") == [], str(post.get("tool_cards")))
check("B3 injects wiped", post.get("injects") == [], str(post.get("injects")))
check("B4 the session still exists (reset keeps it, does not delete)",
      post.get("id") == SID)
check("B5 the task list was reset",
      len((taskgraph.load(SID) or {}).get("nodes") or []) == 0)

check("C1 clearing a missing session returns None", server.clear_session("nope-not-here") is None)

src = open(os.path.join(REPO, "src", "sparkforge", "server.py"), encoding="utf-8").read()
src += open(os.path.join(REPO, "src", "sparkforge", "httpapi.py"), encoding="utf-8").read()
check("D1 the endpoint uses the shared clearer", "clear_session(sid)" in src)
check("D2 the clearer wipes the side stores",
      'sess["tool_cards"] = []' in open(os.path.join(REPO, "src", "sparkforge", "stores.py"), encoding="utf-8").read()
      and 'sess["injects"] = []' in open(os.path.join(REPO, "src", "sparkforge", "stores.py"), encoding="utf-8").read())

print("---")
ok = sum(1 for r in results if r)
print("%d/%d PASS" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)
