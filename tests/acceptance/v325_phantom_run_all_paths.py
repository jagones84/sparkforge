#!/usr/bin/env python3
"""v325 — EVERY turn entry point must register its "running" signal (JAG-325).

Follow-up to the SEVERE phantom-run finding (JAG-323). JAG-323 fixed the
STREAMING path, but two other paths run a real model turn and never touched
`_ACTIVE_CHAT`, so the session list still reported them as idle while the model
burned GPU/tokens (a phantom run):

  * the synchronous `POST /api/chat` handler in server.py;
  * `api_v02.LocalApi.chat` — the in-process MCP `chat` bridge.

The fix is a shared bracket, `turn_begin`/`turn_end`, that ANY entry point uses.

Locked here:
  * `turn_begin(sid)` registers the sid in `_ACTIVE_CHAT` (list_sessions -> running)
    and publishes `chat.run` on the global feed;
  * `turn_end(sid, tok)` clears it and publishes `chat.done`;
  * the per-turn TOKEN guard: an older turn finishing late never un-marks a newer one;
  * the sync `/api/chat` path and the MCP `chat` bridge both call the bracket.

Deterministic, no model. Run: python3 tests/acceptance/v325_phantom_run_all_paths.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-325-")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(TMP, "sessions")
os.environ["LONGRUN_GRAPH_DIR"] = os.path.join(TMP, "graphs")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
os.makedirs(os.environ["LONGRUN_SESSIONS_DIR"], exist_ok=True)
os.makedirs(os.environ["LONGRUN_GRAPH_DIR"], exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun import server  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


def read(*parts):
    with open(os.path.join(REPO, *parts), encoding="utf-8") as f:
        return f.read()


def _row(sid):
    return next((r for r in server.list_sessions() if r["id"] == sid), None)


def _feed_kinds(sid):
    return [e.get("kind") for e in list(server._feed) if e.get("session") == sid]


SID = "v325run"
server.get_or_create_session(SID, "phantom probe")

check("A1 idle before any turn", _row(SID).get("running") is False, str(_row(SID)))

tok = server.turn_begin(SID)
check("A2 turn_begin registers the session as running",
      _row(SID).get("running") is True, str(_row(SID)))
check("A3 turn_begin returns a token", tok is not None)
check("A4 the registration carries ev0 + tok",
      isinstance(server._ACTIVE_CHAT.get(SID), dict)
      and "ev0" in server._ACTIVE_CHAT[SID] and "tok" in server._ACTIVE_CHAT[SID])
check("A5 turn_begin publishes chat.run on the global feed",
      "chat.run" in _feed_kinds(SID), str(_feed_kinds(SID)))

server.turn_end(SID, tok)
check("A6 turn_end clears the running signal", _row(SID).get("running") is False)
check("A7 turn_end publishes chat.done on the global feed",
      "chat.done" in _feed_kinds(SID), str(_feed_kinds(SID)))

# ---- per-turn token guard -------------------------------------------------
SID2 = "v325tok"
server.get_or_create_session(SID2, "token probe")
t1 = server.turn_begin(SID2)
t2 = server.turn_begin(SID2)   # a newer turn replaced the registration
server.turn_end(SID2, t1)      # the OLDER turn finishing late must not clear it
check("B1 a stale token does not clear a newer turn's registration",
      _row(SID2).get("running") is True, str(_row(SID2)))
server.turn_end(SID2, t2)
check("B2 the current token clears it", _row(SID2).get("running") is False)

# ---- wiring: every entry point uses the bracket ---------------------------
srv = read("src", "longrun", "server.py") + read("src", "longrun", "httpapi.py")
ev = read("src", "longrun", "events.py")
check("C1 the shared bracket lives in events.py and is re-exported by server",
      "def turn_begin(" in ev and "def turn_end(" in ev and "turn_begin" in srv)
check("C2 the sync /api/chat path brackets its turn",
      '_turn_tok = turn_begin(sess["id"])' in srv
      and 'turn_end(sess["id"], _turn_tok)' in srv)
check("C3 the sync path releases in a finally (any outcome)",
      "finally:" in srv and 'turn_end(sess["id"], _turn_tok)' in srv)
check("C4 the streaming path still registers (JAG-323 regression)",
      '_ACTIVE_CHAT[sess["id"]] = {"ev0": feed_seq()' in srv)

api2 = read("src", "longrun", "api_v02.py")
check("C5 the in-process MCP chat bridge brackets its turn",
      "srv.turn_begin(sess[\"id\"])" in api2 and "srv.turn_end(sess[\"id\"], tok)" in api2)

print("---")
ok = sum(1 for r in results if r)
print("%d/%d PASS" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)
