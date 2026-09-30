#!/usr/bin/env python3
"""Measure the REAL prompt size assembled by chat_once (sys + transcript + message)."""
import sys

sys.path.insert(0, "/home/jagones/Repositories/sparkforge")
import api_v02  # noqa: E402
import context_engine  # noqa: E402
import server  # noqa: E402

sid = "v06-live-20ed614e"
sess = server.load_session(sid)
msgs = sess.get("messages", [])
msg = msgs[-1].get("content", "") if msgs else ""

tool_ctx = server.CHAT_TOOL_PROMPT + "\n" + api_v02.tool_context()
sysp = (server.SYSTEM_PROMPT + "\n\n" + server.self_summary() + tool_ctx
        + "\n\nCurrent harness state (your persistent task list):\n"
        + server.context_summary(session_id=sid))

ct = context_engine.count_tokens
print("SYSTEM_PROMPT      =", ct(server.SYSTEM_PROMPT))
print("self_summary       =", ct(server.self_summary()))
print("tool_context       =", ct(tool_ctx), " <-- registry dump, huge")
print("context_summary    =", ct(server.context_summary(session_id=sid)))
print("full sys           =", ct(sysp))
print("transcript (stored)=", sum(ct(m.get('content','')) for m in msgs))
print("TOTAL sent ~       =", ct(sysp) + sum(ct(m.get('content','')) for m in msgs) + ct(msg))
print()
print("today /api/context returns x =",
      sum(ct(m.get('content','')) for m in msgs))
