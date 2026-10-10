#!/usr/bin/env python3
"""v316 — session job labels (JX) are never reused (JAG-316).

`_max_job()` used to take the max `job` only over LIVE session files. Deleting
the session that held the top number therefore let the NEXT session reuse it, so
two different sessions could both be labelled `J12` over time — contradicting the
"assigned once, never shifts" contract (JAG-169) and colliding with the
orchestrator's own `J<n>` job ids.

Fix: the counter is backed by a persisted high-water mark (`.jobseq`) and is
monotonic across deletes.

Deterministic, no model. Run:  python3 tests/acceptance/v316_job_id_monotonic.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-316-")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(TMP, "cfg")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(TMP, "sessions")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
os.environ["LONGRUN_GRAPH_DIR"] = os.path.join(TMP, "graphs")
os.environ["LONGRUN_EDITS_DIR"] = os.path.join(TMP, "edits")
os.environ["LONGRUN_RUNS_DIR"] = os.path.join(TMP, "runs")
for d in ("cfg", "sessions", "graphs", "edits", "runs"):
    os.makedirs(os.path.join(TMP, d), exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.core import server  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


def new_session(title):
    return server.get_or_create_session(None, title=title)["job"]


def delete_like_handler(sid):
    server.push_abort(sid)
    with server._deleted_lock:
        server._DELETED_SESSIONS.add(sid)
        server._persist_tombstones()
    return server._purge_session_artifacts(sid)


a = new_session("a")
b = new_session("b")
check("A1 numbers are assigned in order", b == a + 1, "%s->%s" % (a, b))

# delete the session holding the HIGHEST numbe
paths = [fn for fn in os.listdir(server.SESSIONS_DIR) if fn.endswith(".json")]
top_sid = None
for fn in paths:
    s = server.load_session(fn[:-5])
    if s and int(s.get("job") or 0) == b:
        top_sid = fn[:-5]
check("A2 the top session was found", top_sid is not None)
delete_like_handler(top_sid)
check("A3 the top session is gone", server.load_session(top_sid) is None)

c = new_session("c")
check("A4 the next number is NOT reused after deleting the top session",
      c > b, "b=%s c=%s" % (b, c))

# ---- B: the high-water mark is durable -------------------------------------
check("B1 a jobseq file was written", os.path.isfile(server._JOBSEQ_FILE))
check("B2 the high-water mark equals the last assigned", server._read_seq() == c,
      "%s vs %s" % (server._read_seq(), c))

# simulate a restart with every session wiped: the counter must not fall back
for fn in [f for f in os.listdir(server.SESSIONS_DIR) if f.endswith(".json")]:
    os.unlink(os.path.join(server.SESSIONS_DIR, fn))
check("B3 with no sessions the in-memory max still reads the high-water mark",
      server._max_job() == c, str(server._max_job()))
d = new_session("d")
check("B4 a fresh session keeps climbing after a wipe", d > c, "c=%s d=%s" % (c, d))

# ---- C: source wiring ------------------------------------------------------
src = open(os.path.join(REPO, "src", "longrun", "core/server.py"), encoding="utf-8").read()
check("C1 the counter persists a high-water mark", "_write_seq(n)" in open(os.path.join(REPO, "src", "longrun", "memory/stores.py"), encoding="utf-8").read())
check("C2 _max_job starts from the persisted seq", "best = _read_seq()" in open(os.path.join(REPO, "src", "longrun", "memory/stores.py"), encoding="utf-8").read())

print("---")
ok = sum(1 for r in results if r)
print("%d/%d PASS" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)

