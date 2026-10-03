#!/usr/bin/env python3
"""v0.9.21 acceptance — a session is linked to a folder (JAG-115)."""
import json
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
tmp = tempfile.mkdtemp(prefix="sf-ws-")
CFG = os.path.join(tmp, "cfg")
SESS = os.path.join(tmp, "sessions")
os.environ["SPARKFORGE_CONFIG_DIR"] = CFG
os.environ["SPARKFORGE_SESSIONS_DIR"] = SESS
os.environ["SPARKFORGE_DB"] = os.path.join(tmp, "events.db")
os.environ["SPARKFORGE_GRAPH_DIR"] = os.path.join(tmp, "graphs")
os.makedirs(CFG, exist_ok=True)
os.makedirs(SESS, exist_ok=True)
os.makedirs(os.environ["SPARKFORGE_GRAPH_DIR"], exist_ok=True)
A = os.path.join(tmp, "projA")
B = os.path.join(tmp, "projB")
for d in (A, B):
    os.makedirs(os.path.join(d, ".sparkforge", "rules"), exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from sparkforge import api_v02  # noqa: E402
from sparkforge import rules as R  # noqa: E402
from sparkforge import server  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


write(os.path.join(A, ".sparkforge", "RULES.md"), "RULE-A")
write(os.path.join(B, ".sparkforge", "RULES.md"), "RULE-B")

# ---- R1: resolution precedence --------------------------------------------
R.set_workspace(A)  # global default = A
check("R1 session workspace wins over global",
      R.resolve_workspace({"workspace": B}) == B, R.resolve_workspace({"workspace": B}))
check("R1b no session -> global default",
      R.resolve_workspace(None) == A, R.resolve_workspace(None))
check("R1c bad session workspace -> falls back to global",
      R.resolve_workspace({"workspace": "/does/not/exist"}) == A, "")

# ---- R2: ws-aware collect / rules_block -----------------------------------
check("R2 collect(ws=A) sees RULE-A",
      "RULE-A" in R.collect(ws=A)["project"]["text"], "")
check("R2b collect(ws=B) sees RULE-B",
      "RULE-B" in R.collect(ws=B)["project"]["text"], "")
check("R2c rules_block(ws=A) has A not B",
      "RULE-A" in R.rules_block(ws=A) and "RULE-B" not in R.rules_block(ws=A), "")
check("R2d status(ws=B) path points at B",
      R.status(ws=B)["project"]["path"] == os.path.join(B, ".sparkforge", "RULES.md"),
      R.status(ws=B)["project"]["path"])

# ---- R3: ws-aware save ----------------------------------------------------
r = R.save("project", "SPARTA", ws=A)
check("R3 save(ws=A) ok + writes A only",
      r.get("ok") is True and os.path.isfile(os.path.join(A, ".sparkforge", "RULES.md"))
      and "SPARTA" in R.collect(ws=A)["project"]["text"]
      and "SPARTA" not in R.collect(ws=B)["project"]["text"], str(r))

# ---- R4: check_dir --------------------------------------------------------
check("R4 check_dir valid returns abs path", R.check_dir(A) == A, str(R.check_dir(A)))
check("R4b check_dir invalid returns None", R.check_dir("/nope-xyz") is None, "")

# ---- A: API helpers are session-aware ------------------------------------
check("A1 api helpers present",
      all(hasattr(api_v02, n) for n in ("rules_status", "rules_save",
                                        "workspace_get", "workspace_set")), "")

sid = "sesswstest"
server.get_or_create_session(sid, "t")
sess = server.load_session(sid)
check("A2 new session is pinned to the default folder",
      sess.get("workspace") == A, str(sess.get("workspace")))

r = api_v02.workspace_set({"session": sid, "path": B})
check("A3 workspace_set(session) ok", r.get("ok") is True, str(r))
check("A3b session record now pins B",
      server.load_session(sid).get("workspace") == B, str(server.load_session(sid).get("workspace")))
check("A3c global default unchanged (still A)", R.get_workspace() == A, R.get_workspace())

ws = api_v02.workspace_get({"session": sid})
check("A4 workspace_get(session) returns B", ws.get("workspace") == B, str(ws.get("workspace")))

r = api_v02.rules_save({"scope": "project", "content": "SESSRULE", "session": sid})
check("A5 rules_save(session) writes into B",
      r.get("ok") is True and os.path.isfile(os.path.join(B, ".sparkforge", "RULES.md"))
      and "SESSRULE" in R.collect(ws=B)["project"]["text"], str(r))

st = api_v02.rules_status({"session": sid})
check("A6 rules_status(session) resolves B",
      st["project"]["path"] == os.path.join(B, ".sparkforge", "RULES.md"), st["project"]["path"])

r = api_v02.workspace_set({"session": sid, "path": "/nope-xyz"})
check("A7 invalid path rejected", r.get("ok") is False, str(r))

r = api_v02.workspace_set({"path": B, "set_default": True})
check("A8 set_default updates the global default",
      r.get("ok") is True and R.get_workspace() == B, str(r))

# ---- S: list_sessions exposes the pinned workspace ------------------------
listing = [s for s in server.list_sessions() if s["id"] == sid]
check("S1 list_sessions exposes workspace", listing and listing[0].get("workspace") == B,
      str(listing))

total = len(results)
passed = sum(results)
print("\n==== %d/%d checks passed ====" % (passed, total))
sys.exit(0 if passed == total else 1)
