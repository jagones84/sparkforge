#!/bin/bash
set -e
cd /home/jagones/Repositories/sparkforge
git add sandbox.py tools.py api_v02.py server.py
cat > /tmp/jag68h <<'MSGEOF'
JAG-68: stop a running tool (kill the job, not just the socket)

The chat/agent STOP only dropped the SSE socket; the tool subprocess kept
running on the DGX until its 900s timeout. sandbox.run now executes via Popen
with start_new_session and registers the job (job_id = run_id); sandbox.cancel()
SIGTERMs -> SIGKILLs the whole process group (and `docker kill`s a docker job).
New API: GET /api/tools/running, POST /api/tools/cancel {job|run_id}. chat_once
passes run_id=session so a chat tool is cancellable; chat.run now carries the
session id so the app knows what to cancel.

Evidence: trash/test_cancel.py -> sleep 120 killed in 1.27s, call returned in
2.0s, result.cancelled=true exit_code=130.
MSGEOF
git commit -F /tmp/jag68h
git log -1 --oneline

cd /home/jagones/Repositories/sparkpulse-app
git add app/src/main/java/com/jagones/sparkpulse/ForgeScreen.kt app/build.gradle.kts
cat > /tmp/jag68a <<'MSGEOF'
JAG-68: STOP also kills the running tool on the server

stop() now POSTs /api/tools/cancel {run_id: session} before dropping the socket,
so a long shell/MCP job is actually terminated instead of continuing silently.
v1.6.15 (versionCode 23). Build + install OK on oneplus-15r.
MSGEOF
git commit -F /tmp/jag68a
git log -1 --oneline
