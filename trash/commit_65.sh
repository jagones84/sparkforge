#!/bin/bash
cd /home/jagones/Repositories/sparkforge
git add server.py tests/mock_router.py tests/v06_taskgraph.py
cat > /tmp/jag65msg <<'MSGEOF'
JAG-65: todo list authored inline by the model (no blocking planner pre-flight)

The chat path ran a SEPARATE blocking planner model call (generate_from_model)
before every reply: ~12s of dead air right after the write_todos card, and it
was fed ONLY the raw user message, so it parroted that message back as steps.

Now the model authors the list INLINE on its own first response via the harness
action {"action":"write_todos","todos":[...]} -- exactly how Claude Code / Deep
Agents work. chat_once maps it onto the session graph, streams graph.node.added
plus a normal tool.call/tool.result card, and the list stays persistent and
session-keyed (render_todos is re-injected every turn).

Also stream the model's reasoning (chat.delta channel=think) live during tool
steps, so a multi-call turn shows progress instead of appearing frozen; only
answer text is buffered, so raw tool-call JSON is never shown to the user.

Acceptance: tests/v06_taskgraph.py 16/16 (live C1: 0.2s to 3 nodes, chat.delta
streamed first).
MSGEOF
git commit -F /tmp/jag65msg
git log -1 --oneline
