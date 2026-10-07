#!/usr/bin/env python3
"""v302 — in-memory per-session runtime leaks (JAG-302).

The disk side of a session delete was already handled (JAG-179). These maps are
keyed by session id and had NO pruning, so they grew across every create / chat /
delete cycle:

  * `STEER_INBOX` — `drain_steer` re-inserted an EMPTY list on every loop, leaving
    a permanent entry for every session that ever ran a turn;
  * `_REAL_PROMPT_TOKENS` / `_REAL_CACHED_TOKENS` — the measured ctx cache;
  * `_TURN_LOCKS` — one lock per session, never released;
  * `ABORT_INBOX` — a delete of an IDLE session left its abort flag forever.

Locked here: `drain_steer` pops its key; `_forget_session_runtime` drops every
per-session entry on delete, while KEEPING the abort flag if a turn is still live.

Deterministic, no live model. Run: python3 tests/v302_runtime_leak.py
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "src"))
sys.path.insert(0, os.path.join(REPO, "src2"))

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


def read(*parts):
    with open(os.path.join(REPO, *parts), encoding="utf-8") as f:
        return f.read()


from sparkforge import server as srv  # noqa: E402

SID = "v302leak"

# --- steer inbox does not accumulate empty entries --------------------------
srv.push_steer(SID, "hello")
check("steer queued", srv.has_steer(SID) is True)
check("drain returns the queued text", srv.drain_steer(SID) == ["hello"])
check("drain leaves NO empty entry behind", SID not in srv.STEER_INBOX)
check("drain on an empty session returns []", srv.drain_steer(SID) == [])
check("drain on an empty session creates no key", SID not in srv.STEER_INBOX)

# --- forget_session_runtime drops every per-session entry -------------------
srv.STEER_INBOX[SID] = ["x"]
srv.ABORT_INBOX.add(SID)
srv._REAL_PROMPT_TOKENS[SID] = 111
srv._REAL_CACHED_TOKENS[SID] = 22
srv._TURN_LOCKS[SID] = object()
srv._forget_session_runtime(SID)
check("steer entry cleared", SID not in srv.STEER_INBOX)
check("abort flag cleared when the session is idle", SID not in srv.ABORT_INBOX)
check("ctx cache cleared",
      SID not in srv._REAL_PROMPT_TOKENS and SID not in srv._REAL_CACHED_TOKENS)
check("turn lock cleared", SID not in srv._TURN_LOCKS)

# the active-chat registration is dropped too
SID3 = "v302leak3"
srv._ACTIVE_CHAT[SID3] = {"ev0": 0, "ts": 0, "tok": object()}
srv._forget_session_runtime(SID3)
check("active-chat entry cleared", SID3 not in srv._ACTIVE_CHAT)

# --- a LIVE turn must keep its abort flag -----------------------------------
SID2 = "v302leak2"
srv.push_abort(SID2)
srv._ACTIVE_CHAT[SID2] = {"ev0": 0, "ts": 0, "tok": object()}
srv._forget_session_runtime(SID2)
check("abort flag kept while a turn is still live", srv._is_aborted(SID2) is True)
check("the live turn's active-chat entry is still dropped",
      SID2 not in srv._ACTIVE_CHAT)
srv.clear_abort(SID2)

# ------------------------------------------------------------- source locks
s = read("src", "sparkforge", "server.py")
check("drain_steer pops its key (no empty re-insert)",
      "return STEER_INBOX.pop(sess_id, [])" in s)
check("delete path forgets the session runtime", "_forget_session_runtime(sid)" in s)
check("runtime cleanup pops the ctx cache", "_REAL_PROMPT_TOKENS.pop(sid, None)" in s)
check("runtime cleanup pops the turn lock", "_TURN_LOCKS.pop(sid, None)" in s)

print("---")
passed = sum(results)
print("%d/%d PASS" % (passed, len(results)))
sys.exit(0 if passed == len(results) else 1)
