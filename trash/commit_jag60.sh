#!/bin/bash
# JAG-58c fix (app: approval REST off main thread) + JAG-60 (SSE heartbeat)
set -e

cd /home/jagones/Repositories/sparkpulse-app
git add app/build.gradle.kts app/src/main/java/com/jagones/sparkpulse/ForgeScreen.kt
git commit -m "fix(forge): run approval REST off the main thread

refreshApprovals()/decideApproval() called rest.text() directly inside
viewModelScope.launch (Main dispatcher) -> NetworkOnMainThreadException,
swallowed by runCatching, so the pending queue was always empty: the
Approve/Deny banner never appeared and the buttons silently did nothing.
Wrap both in withContext(Dispatchers.IO) like every other refresh.
1.6.10 (versionCode 18)."
echo "--- sparkpulse-app ---"
git log -1 --oneline

cd /home/jagones/Repositories/sparkforge
git add api_v02.py server.py
git commit -m "fix(sse): heartbeat keeps the channel alive while awaiting approval

A run blocked on the approval gate left the SSE stream silent for up to
300s, so mobile networks/proxies aborted it (Software caused connection
abort). Emit a ': ping' SSE comment every ~10s whenever the producer is
silent (agent_stream_gen_v2 + sse_pump). Clients ignore SSE comments."
echo "--- sparkforge ---"
git log -1 --oneline
echo "DONE"
