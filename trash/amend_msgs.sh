#!/bin/bash
set -e
cd /home/jagones/Repositories/sparkforge
cat > /tmp/sf_msg.txt <<'EOF'
JAG-63: unify graph+tasks into ONE persistent, session-keyed task list

- taskgraph: graph keyed by SESSION (one task = one session), subtasks via
  `parent`, new `reset` and `render_todos`, `all_done` helper.
- server: context_summary(session_id/graph_key) injects the persistent task
  list into every chat and agent prompt; chat no longer force-closes the list
  at the end of each message; a new task (list fully done) starts fresh;
  POST /api/sessions/<id>/graph/reset.
- stop injecting the parallel tasks.json board.
- tests/v06_taskgraph updated to the new contract. 16/16 checks pass.
EOF
git commit --amend -F /tmp/sf_msg.txt >/dev/null
cd /home/jagones/Repositories/sparkpulse-app
cat > /tmp/sp_msg.txt <<'EOF'
JAG-62: lateral collapsible panels bar (v1.6.12)

The SESSIONI/GRAFO/COMPACTION/CoT chip row became a lateral, collapsible bar:
a freccetta expands it into a nav column plus the selected panel, so the
transcript is never pushed down.
EOF
git commit --amend -F /tmp/sp_msg.txt >/dev/null
echo "--- sparkforge ---"
git -C /home/jagones/Repositories/sparkforge log --oneline -n 1
echo "--- sparkpulse-app ---"
git -C /home/jagones/Repositories/sparkpulse-app log --oneline -n 1
rm -f /tmp/sf_msg.txt /tmp/sp_msg.txt
