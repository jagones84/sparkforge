#!/usr/bin/env python3
"""v0.9.22 acceptance — WebUI fixes #1/#2/#4 (JAG-116)."""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
tmp = tempfile.mkdtemp(prefix="sf-116-")
os.environ["SPARKFORGE_CONFIG_DIR"] = os.path.join(tmp, "cfg")
os.environ["SPARKFORGE_SESSIONS_DIR"] = os.path.join(tmp, "sessions")
os.environ["SPARKFORGE_DB"] = os.path.join(tmp, "events.db")
os.environ["SPARKFORGE_GRAPH_DIR"] = os.path.join(tmp, "graphs")
for k in ("config_dir", "sessions", "graphs"):
    os.makedirs(os.path.join(tmp, k), exist_ok=True)
sys.path.insert(0, REPO)

import server  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


def new_sess(sid):
    s = {"id": sid, "title": sid, "created": 0, "messages": []}
    server.save_session(s)
    return s


# ---- T1: write_todos card carries input AND output ------------------------
evs = []
sess = new_sess("s116a")
server._apply_chat_todos(sess, {"todos": ["primo", "secondo"]},
                         lambda kind, **d: evs.append((kind, d)))
call = [d for k, d in evs if k == "tool.call"]
res = [d for k, d in evs if k == "tool.result"]
check("T1 tool.call for write_todos carries args",
      call and call[0].get("args", {}).get("todos"), str(call[0].get("args") if call else None))
check("T1b tool.result for write_todos carries output",
      res and res[0].get("output") and "primo" in res[0]["output"],
      str(res[0].get("output") if res else None))
check("T1c tool.result also carries args (input visible)",
      res and res[0].get("args", {}).get("todos"), "")

# ---- T2: update_todos card carries input AND output -----------------------
evs2 = []
sess2 = new_sess("s116b")
server._apply_chat_todos(sess2, {"todos": ["alpha", "beta"]}, lambda k, **d: None)
server._apply_chat_todo_updates(sess2, {"steps": [{"index": 0, "status": "doing"}]},
                                lambda kind, **d: evs2.append((kind, d)))
r2 = [d for k, d in evs2 if k == "tool.result"]
c2 = [d for k, d in evs2 if k == "tool.call"]
check("T2 update_todos tool.call carries steps",
      c2 and c2[0].get("args", {}).get("steps"), str(c2[0].get("args") if c2 else None))
check("T2b update_todos tool.result carries output",
      r2 and r2[0].get("output"), str(r2[0].get("output") if r2 else None))

# ---- T3: WebUI static — the three fixes are present -----------------------
html = open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8").read()
check("T3 model button is legible (color var(--txt))",
      ".model-btn { cursor: pointer; color: var(--txt)" in html, "")
check("T3b jump-to-bottom button exists", 'id="jumpBtn"' in html and "function updateJump" in html, "")
check("T3c scroll no longer always forces the bottom",
      "if (l && _stick) l.scrollTop" in html and "_nearBottom" in html, "")
check("T3d jump button is wired",
      '$("jumpBtn").onclick' in html and '$("log").addEventListener("scroll"' in html, "")

total = len(results)
passed = sum(results)
print("\n==== %d/%d checks passed ====" % (passed, total))
sys.exit(0 if passed == total else 1)
