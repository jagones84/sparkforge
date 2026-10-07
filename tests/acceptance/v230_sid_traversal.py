#!/usr/bin/env python3
"""v230 — a client-supplied session id must never escape the sessions dir (JAG-230).

The `session` parameter arrives verbatim from the wire (query string or JSON
body) and was concatenated into a file path: `data/sessions/<sid>.json`. A sid
like `../../foo` therefore let an attacker READ an arbitrary `*.json`, WRITE a
transcript over it, or (via the delete endpoint / artifact purge) UNLINK files
outside the store. `_valid_sid()` now rejects any id that is not a plain token
(no path separator, no `..`, string type, bounded length) and every fs-touching
helper refuses it.

Deterministic, isolated temp dir, no network. Run:  python3 tests/v230_sid_traversal.py
"""
import atexit
import os
import shutil
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_tmp = tempfile.mkdtemp(prefix="sf-230-")
atexit.register(lambda: shutil.rmtree(_tmp, ignore_errors=True))
# Isolate BEFORE importing the server (paths are read at import time).
os.environ["SPARKFORGE_SESSIONS_DIR"] = os.path.join(_tmp, "sessions")
os.environ["SPARKFORGE_GRAPH_DIR"] = os.path.join(_tmp, "graphs")
os.environ["SPARKFORGE_RUNS_DIR"] = os.path.join(_tmp, "runs")
os.environ["SPARKFORGE_EDITS_DIR"] = os.path.join(_tmp, "edits")
os.environ["SPARKFORGE_CONFIG_DIR"] = os.path.join(_tmp, "cfg")
os.environ["SPARKFORGE_DB"] = os.path.join(_tmp, "events.db")
sys.path.insert(0, os.path.join(REPO, "src"))
from sparkforge import server  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


SESS = server.SESSIONS_DIR
os.makedirs(SESS, exist_ok=True)

# ---- _valid_sid: accept real ids, reject traversal/type-confusion ----
for good in ("991db778424b", "v062-live-c47f39", "JX.TY", "a", "A_b-1.2"):
    check("valid id accepted: " + good, server._valid_sid(good))
for bad in ("../../etc/passwd", "..", "a/b", "a\\b", "a\x00b", "", None, 123,
            "a" * 121, "./x", "../x"):
    check("unsafe id rejected: %r" % bad, not server._valid_sid(bad))

# ---- load_session must not escape the store ----
# plant a secret .json one level above the sessions dir
secret = os.path.join(os.path.dirname(SESS), "secret.json")
with open(secret, "w", encoding="utf-8") as f:
    f.write('{"leak": "TOP-SECRET"}')
got = server.load_session("../secret")
check("load_session('../secret') returns None", got is None, repr(got)[:60])
got2 = server.load_session("../../etc/hosts")
check("load_session('../../etc/hosts') returns None", got2 is None, repr(got2)[:60])

# ---- save_session must not write outside the store ----
evil = os.path.join(_tmp, "evil.json")
server.save_session({"id": "../evil", "title": "x", "messages": []})
check("save_session('../evil') wrote NOTHING outside", not os.path.exists(evil))
server.save_session({"id": "../../escape", "title": "x", "messages": []})
check("save_session('../../escape') wrote NOTHING outside",
      not os.path.isfile(os.path.join(_tmp, "escape.json")))

# ---- get_or_create_session must allocate a SAFE id, never honour a bad one ----
s = server.get_or_create_session("../../pwn")
sid = s.get("id")
check("get_or_create_sanitises to a safe id", server._valid_sid(sid), "id=%r" % sid)
inside = os.path.join(SESS, sid + ".json")
check("the sanitised session persists INSIDE the store", os.path.isfile(inside))
check("no 'pwn.json' created one level up",
      not os.path.exists(os.path.join(os.path.dirname(SESS), "pwn.json")))

# ---- _purge_session_artifacts must refuse an unsafe id for unlink() ----
victim = os.path.join(os.path.dirname(SESS), "keepme.json")
with open(victim, "w", encoding="utf-8") as f:
    f.write("{}")
removed = server._purge_session_artifacts("../keepme")
check("purge returns nothing for an unsafe id", removed == [], "removed=%r" % removed)
check("purge did NOT unlink outside the store", os.path.isfile(victim))

print("---")
ok = sum(results)
print("%d/%d PASS" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)
