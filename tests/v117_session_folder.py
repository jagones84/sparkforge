#!/usr/bin/env python3
"""v0.9.23 acceptance — every session gets a folder (JAG-117)."""
import json
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
tmp = tempfile.mkdtemp(prefix="sf-117-")
os.environ["SPARKFORGE_CONFIG_DIR"] = os.path.join(tmp, "cfg")
os.environ["SPARKFORGE_SESSIONS_DIR"] = os.path.join(tmp, "sessions")
os.environ["SPARKFORGE_DB"] = os.path.join(tmp, "events.db")
os.environ["SPARKFORGE_GRAPH_DIR"] = os.path.join(tmp, "graphs")
for k in ("cfg", "sessions", "graphs"):
    os.makedirs(os.path.join(tmp, k), exist_ok=True)
A = os.path.join(tmp, "projA")
B = os.path.join(tmp, "projB")
os.makedirs(A, exist_ok=True)
os.makedirs(B, exist_ok=True)
sys.path.insert(0, REPO)

import rules as R  # noqa: E402
import server  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


R.set_workspace(A)  # global default = A

# ---- S1: a new session is pinned to the default folder --------------------
s1 = server.get_or_create_session(None, "t1")
check("S1 new session pinned to default", s1.get("workspace") == A, str(s1.get("workspace")))

# ---- S2: explicit folder on creation wins ---------------------------------
s2 = server.get_or_create_session(None, "t2", workspace=B)
check("S2 explicit folder on creation", s2.get("workspace") == B, str(s2.get("workspace")))

# ---- S3: an existing session without a folder is backfilled ---------------
sess = {"id": "legacy1", "title": "legacy", "created": 0, "messages": []}
server.save_session(sess)
s3 = server.get_or_create_session("legacy1")
check("S3 existing session gets a folder on load", s3.get("workspace") == A, str(s3.get("workspace")))
check("S3b it was persisted", server.load_session("legacy1").get("workspace") == A, "")

# ---- S4: backfill sweeps every stored session -----------------------------
sess2 = {"id": "legacy2", "title": "legacy2", "created": 0, "messages": []}
server.save_session(sess2)
n = server.backfill_session_workspaces()
check("S4 backfill pins the unfiled session", server.load_session("legacy2").get("workspace") == A
      and n >= 1, "n=%d" % n)

# ---- S5: an invalid folder argument falls back to the default -------------
s5 = server.get_or_create_session(None, "t5", workspace="/nope-xyz")
check("S5 invalid folder -> default", s5.get("workspace") == A, str(s5.get("workspace")))

# ---- S6: list_sessions exposes the folder ---------------------------------
row = [x for x in server.list_sessions() if x["id"] == s2["id"]]
check("S6 list exposes the folder", row and row[0].get("workspace") == B, str(row))

# ---- T: WebUI static -------------------------------------------------------
html = open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8").read()
check("T webui asks the folder on new session",
      'id="newSessDlg"' in html and "async function createNewSession" in html
      and 'id="nsWs"' in html, "")

total = len(results)
passed = sum(results)
print("\n==== %d/%d checks passed ====" % (passed, total))
sys.exit(0 if passed == total else 1)
