#!/usr/bin/env python3
"""v0.7.7 acceptance — "act, don't announce" + MCP session recovery (JAG-74).

Proves two real user-reported failures are closed:
  * the agent said "Carico un'altra skill…" and did nothing (prose promise, no tool);
  * pmcp tools all failed with "Session not found" until a restart.
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
tmp = tempfile.mkdtemp(prefix="sf-act-")
os.environ["SPARKFORGE_SESSIONS_DIR"] = os.path.join(tmp, "sessions")
os.environ["SPARKFORGE_DB"] = os.path.join(tmp, "events.db")
os.environ["SPARKFORGE_GRAPH_DIR"] = os.path.join(tmp, "graphs")
os.makedirs(os.environ["SPARKFORGE_SESSIONS_DIR"], exist_ok=True)
os.makedirs(os.environ["SPARKFORGE_GRAPH_DIR"], exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from sparkforge import mcp_client  # noqa: E402
from sparkforge import server  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


# --- predicate: a promise is NOT a result -------------------------------------
check("A1 a short first-person promise is detected",
      server._looks_like_promise("Carico un'altra skill per dimostrare che funziona.") is True)
check("A2 an English promise is detected",
      server._looks_like_promise("I'll load another skill now.") is True)
check("A3 a real RESULT is not a promise",
      server._looks_like_promise("Ho caricato la skill: ecco l'elenco completo.") is False)
check("A4 a long answer is never treated as a promise",
      server._looks_like_promise("Carico " + "x" * 500) is False)
check("A5 empty text is not a promise", server._looks_like_promise("") is False)

# --- integration: the turn actually nudges the model to act -------------------
seq = [
    ("Carico un'altra skill per dimostrare che funziona.", "", "m1"),
    ('{"action":"tool","tool":"skills","args":{"action":"list"}}', "", "m1"),
    ("Fatto: la skill è stata caricata e verificata.", "", "m1"),
]
calls = {"n": 0}


def fake_stream(msgs, model, kind, on_delta, timeout=300, usage=None):
    calls["n"] += 1
    return seq.pop(0) if seq else ("Fine.", "", model)


server.stream_with_fallback = fake_stream
server.api_v02.gated_call = lambda tool, args, run_id=None: {
    "status": "executed", "observation": "skill list ok"}
sess = server.get_or_create_session("act-test")
reply, _ = server.chat_once(sess, "carica un'altra skill", None)
check("A6 the announcement triggered a nudge (>=3 model calls, tool then prose)",
      calls["n"] >= 3, "calls=%d" % calls["n"])
check("A7 the stored reply is the real RESULT, not the announcement",
      "Carico un'altra skill" not in reply.get("content", ""),
      "content=%s" % (reply.get("content", "")[:60]))

# --- MCP session recovery -----------------------------------------------------
check("M1 'Session not found' is recognised as an expired MCP session",
      mcp_client._mcp_session_expired(
          {"error": {"code": 404, "message": "Session not found"}}) is True)
check("M2 an unrelated error is NOT treated as expired",
      mcp_client._mcp_session_expired(
          {"error": {"code": -32601, "message": "Method not found"}}) is False)
check("M3 a normal result is not an error",
      mcp_client._mcp_session_expired({"result": {"ok": True}}) is False)

print("\n==== %d/%d checks passed ====" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
