#!/usr/bin/env python3
"""v222 — deleting a session WHILE its turn runs must NOT resurrect it.

Regression (JAG-222): the DELETE handler removed the files but did not abort the
running turn; the worker then persisted the final reply and RECREATED the session
file (measured live: deleted mid-turn -> the transcript came back with the full
answer). Fix: DELETE aborts the turn and tombstones the id; `save_session` skips
a tombstoned id. JAG-315 strengthened this: a load of a deleted id no longer
resurrects it either — the caller gets a FRESH session and the tombstone stays
(see `v315_session_delete_final.py`).

Deterministic, no model. Run:  python3 tests/v222_delete_running.py
"""
import os
import sys
import tempfile
import threading
import time

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
tmp = tempfile.mkdtemp(prefix="sf-222-")
os.environ["SPARKFORGE_CONFIG_DIR"] = os.path.join(tmp, "cfg")
os.environ["SPARKFORGE_SESSIONS_DIR"] = os.path.join(tmp, "sessions")
os.environ["SPARKFORGE_DB"] = os.path.join(tmp, "events.db")
os.environ["SPARKFORGE_GRAPH_DIR"] = os.path.join(tmp, "graphs")
os.environ["SPARKFORGE_EDITS_DIR"] = os.path.join(tmp, "edits")
os.environ["SPARKFORGE_RUNS_DIR"] = os.path.join(tmp, "runs")
for d in ("cfg", "sessions", "graphs", "edits", "runs"):
    os.makedirs(os.path.join(tmp, d), exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from sparkforge import server  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


def spath(sid):
    return os.path.join(server.SESSIONS_DIR, sid + ".json")


def delete_like_handler(sid):
    """Mirror the JAG-222 DELETE handler body (abort + tombstone + purge)."""
    server.push_abort(sid)
    with server._deleted_lock:
        server._DELETED_SESSIONS.add(sid)
    return server._purge_session_artifacts(sid)


# ---- A: create, then a late write cannot resurrect -------------------------
SID = "v222a"
s = server.get_or_create_session(SID, title="t")
check("A1 the session file exists after creation", os.path.isfile(spath(SID)))

server.clear_abort(SID)
delete_like_handler(SID)
check("A2 the file is gone after the delete", not os.path.isfile(spath(SID)))
check("A3 the running turn is abort-signalled", server._is_aborted(SID) is True)

server.append_message(s, "assistant", "late reply from the worker")
server.save_session(s)
check("A4 a late worker write does NOT resurrect the file",
      not os.path.isfile(spath(SID)))

# ---- C: a concurrent worker saving after deletion also cannot resurrect ----
SID2 = "v222c"
s2 = server.get_or_create_session(SID2, title="t2")
server.clear_abort(SID2)


def late_worker():
    time.sleep(0.25)
    server.append_message(s2, "assistant", "reply after delete")
    server.save_session(s2)


th = threading.Thread(target=late_worker)
th.start()
delete_like_handler(SID2)
th.join()
check("C1 a concurrent late worker cannot resurrect the file",
      not os.path.isfile(spath(SID2)), "exists=%s" % os.path.isfile(spath(SID2)))

# ---- B: a deleted id is NEVER resurrected (JAG-315 strengthened JAG-222) ---
s3 = server.get_or_create_session(SID, title="again")
check("B1 a deleted id is not resurrected", s3["id"] != SID, s3["id"])
check("B2 the tombstone is retained", SID in server._DELETED_SESSIONS)
check("B3 the deleted transcript is not rewritten", not os.path.isfile(spath(SID)))

print("---")
ok = sum(1 for r in results if r)
print("%d/%d PASS" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)
