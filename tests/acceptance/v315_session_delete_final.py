#!/usr/bin/env python3
"""v315 — deleting a session is FINAL (JAG-315).

JAG-222 tombstoned a deleted session id and blocked late writes, but
`get_or_create_session(sid)` still DISCARDED the tombstone, so `/api/chat` and
`/api/chat/stream` (which both call it with the client's session id) silently
resurrected a just-deleted session as an empty transcript. Measured:

    created sid=X
    after_delete tombstoned=True
    after_chat get_or_create -> id=X tombstoned=False file_exists=True   # BUG

JAG-315 makes the tombstone authoritative and durable:
  * a load of a deleted id hands back a FRESH session (never the dead id);
  * the tombstone is retained in-memory and persisted to disk, so it also
    survives a server restart (the old set was in-memory only).

Deterministic, no model. Run:  python3 tests/acceptance/v315_session_delete_final.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-315-")
os.environ["SPARKFORGE_CONFIG_DIR"] = os.path.join(TMP, "cfg")
os.environ["SPARKFORGE_SESSIONS_DIR"] = os.path.join(TMP, "sessions")
os.environ["SPARKFORGE_DB"] = os.path.join(TMP, "events.db")
os.environ["SPARKFORGE_GRAPH_DIR"] = os.path.join(TMP, "graphs")
os.environ["SPARKFORGE_EDITS_DIR"] = os.path.join(TMP, "edits")
os.environ["SPARKFORGE_RUNS_DIR"] = os.path.join(TMP, "runs")
for d in ("cfg", "sessions", "graphs", "edits", "runs"):
    os.makedirs(os.path.join(TMP, d), exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from sparkforge import server  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


def spath(sid):
    return os.path.join(server.SESSIONS_DIR, sid + ".json")


def delete_like_handler(sid):
    """Mirror the DELETE handler body (abort + tombstone + persist + purge)."""
    server.push_abort(sid)
    with server._deleted_lock:
        server._DELETED_SESSIONS.add(sid)
        server._persist_tombstones()
    return server._purge_session_artifacts(sid)


# ---- A: a deleted id is not resurrected by a chat-style load ---------------
SID = "v315a"
server.get_or_create_session(SID, title="victim")
check("A1 the file exists after creation", os.path.isfile(spath(SID)))

delete_like_handler(SID)
check("A2 the file is gone after the delete", not os.path.isfile(spath(SID)))
check("A3 the id is tombstoned", SID in server._DELETED_SESSIONS)

again = server.get_or_create_session(SID)   # what /api/chat and /api/chat/stream do
check("A4 a deleted id is NOT resurrected", again.get("id") != SID, str(again.get("id")))
check("A5 the tombstone is retained", SID in server._DELETED_SESSIONS)
check("A6 the deleted transcript is not rewritten", not os.path.isfile(spath(SID)))
check("A7 the caller got a usable fresh session", os.path.isfile(spath(again["id"])))

# ---- B: the tombstone is durable (survives a restart) ----------------------
check("B1 a tombstone file was written", os.path.isfile(server._TOMBSTONE_FILE))
with open(server._TOMBSTONE_FILE, encoding="utf-8") as f:
    body = f.read()
check("B2 the tombstone file lists the id", SID in body.split())

# simulate a restart: drop the in-memory set, reload from disk
with server._deleted_lock:
    server._DELETED_SESSIONS.clear()
server._load_tombstones()
check("B3 the tombstone survives a reload", SID in server._DELETED_SESSIONS)

# ---- C: source wiring ------------------------------------------------------
src = open(os.path.join(REPO, "src", "sparkforge", "server.py"), encoding="utf-8").read()
src += open(os.path.join(REPO, "src", "sparkforge", "httpapi.py"), encoding="utf-8").read()
check("C1 the delete handler persists tombstones", "_persist_tombstones()" in src)
check("C2 a deleted id is not silently recreated", "if _gone:" in open(os.path.join(REPO, "src", "sparkforge", "stores.py"), encoding="utf-8").read())
check("C3 the old unconditional discard is gone", "_DELETED_SESSIONS.discard(sid)" not in src)

print("---")
ok = sum(1 for r in results if r)
print("%d/%d PASS" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)
