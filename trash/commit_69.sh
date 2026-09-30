#!/bin/bash
cd /home/jagones/Repositories/sparkforge
git add hooks.py config/hooks.yaml tools.py server.py api_v02.py tests/v073_hooks.py
cat > /tmp/jag69h <<'MSGEOF'
JAG-69: deterministic lifecycle hooks (PreToolUse / PostToolUse / Stop)

Frontier harnesses wrap the loop with deterministic shell hooks -- the model is
not consulted, the exit code decides. New hooks.py + config/hooks.yaml (ships
EMPTY and documented, so default behaviour is unchanged). tools.execute runs
PreToolUse before dispatch (exit 2 BLOCKS the call, Claude Code contract;
block_on_fail makes any non-zero advisory failure block too) and PostToolUse
with the observation; chat_once and the agent run fire Stop. Every hook emits a
`hook.run` feed event; GET /api/hooks lists them.

Acceptance: tests/v073_hooks.py 4/4 (block, non-matched execute, audit log).
MSGEOF
git commit -F /tmp/jag69h
git log -1 --oneline
