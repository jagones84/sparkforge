#!/bin/bash
# JAG-58 commits: FORGE approvals + expandable tool cards, tool-aware chat, status fix
set -e

cd /home/jagones/Repositories/sparkpulse-app
git add app/build.gradle.kts app/src/main/java/com/jagones/sparkpulse/ForgeScreen.kt app/src/test/java/com/jagones/sparkpulse/ForgeParseTest.kt
git commit -m "feat(forge): approve/deny banner + expandable tool cards

The FORGE tab could not answer an approval.request, so any required tool
(shell/fs.write/git) hung the run until the 300s server timeout. Add an
always-visible Approve/Deny banner above the input bars plus a continuous
pending-approval poll, and make the inline tool card tap-to-expand its
input (args), output (stdout) and error (stderr).

- ForgeScreen.kt: approval banner + poll; ForgeToolCard.args/error;
  applyToolResult keeps the captured args; ForgeToolCardView expandable.
- ForgeParseTest.kt: +2 tests (input/output/error capture + args merge).
- build.gradle.kts: 1.6.9 (versionCode 17)."
echo "--- sparkpulse-app ---"
git log -1 --oneline

cd /home/jagones/Repositories/sparkforge
git add api_v02.py server.py tests/v072_tool_use_acceptance.py
git commit -m "feat(agent): tool-aware chat, no-progress guard, tool.result I/O

- chat_once runs the same tool loop as the agent (skills/MCP/fs/shell)
  behind the approval gate, so chat and agent share tool capabilities.
- agent_run_v2 stops repeating the same action instead of burning max_steps.
- tool.result SSE now carries stdout/stderr/duration_ms for the UI.
- tests/v072_tool_use_acceptance.py: TDD acceptance (6/6)."
echo "--- sparkforge ---"
git log -1 --oneline

cd /home/jagones/Repositories/sparkpulse-server
git add status_server.py
git commit -m "fix(status): ThreadingHTTPServer so the endpoint cannot hang

A single stuck request froze the single-threaded HTTPServer for ~24h,
making SparkPulse report the DGX OFFLINE. Serve with ThreadingHTTPServer
(+daemon threads) and bound every connection with a 15s socket timeout."
echo "--- sparkpulse-server ---"
git log -1 --oneline

echo "ALL COMMITS DONE"
