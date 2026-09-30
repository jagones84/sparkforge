#!/usr/bin/env python3
"""Measure the ctx indicator discrepancy: transcript-only vs real prompt tokens."""
import sys

sys.path.insert(0, "/home/jagones/Repositories/sparkforge")
import context_engine  # noqa: E402
import server  # noqa: E402

sessions = server.list_sessions()
print("sessions:", [s["id"] for s in sessions[:6]])
if not sessions:
    raise SystemExit("no session")
sid = sessions[0]["id"]
sess = server.load_session(sid)
msgs = sess.get("messages", [])
transcript_only = sum(context_engine.count_tokens(m.get("content", "")) for m in msgs)

st = context_engine.preview(sid)
budget = server.context_budget()
print("session        =", sid, "messages =", len(msgs))
print("transcript_only=", transcript_only, "  <-- what /api/context returns today")
print("final_tokens   =", st.get("final_tokens"), "  <-- what is really sent")
print("sys_prompt_tok =", context_engine.count_tokens(server.SYSTEM_PROMPT))
print("budget         =", budget)
print("delta          =", (st.get("final_tokens") or 0) - transcript_only)
