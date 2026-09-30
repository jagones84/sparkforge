#!/bin/bash
set -e
rm -f /home/jagones/shot_rail.png /home/jagones/shot_rail2.png 2>/dev/null || true
cd /home/jagones/Repositories/sparkforge
git add taskgraph.py server.py api_v02.py tests/v06_taskgraph.py
git commit -m "JAG-63: unify graph+tasks into ONE persistent, session-keyed task list

- taskgraph: the graph is keyed by SESSION (one task = one session) instead of
  a single run; subtasks via new `parent`; add `reset` and `render_todos`;
  `all_done` helper.
- server: context_summary(session_id/graph_key) injects the persistent task
  list into every chat and agent prompt; chat no longer force-closes the list
  at the end of each message (that is why it could never persist); a new task
  (list fully done) starts a fresh list; POST /api/sessions/<id>/graph/reset.
- stop injecting the parallel tasks.json board (source of graph/todo confusion).
- tests/v06_taskgraph: updated to the new contract (session-keyed, persists,
  no duplicates on a 2nd message). 16/16 checks pass."
cd /home/jagones/Repositories/sparkpulse-app
git add app/src/main/java/com/jagones/sparkpulse/ForgePanels.kt app/build.gradle.kts
git commit -m "JAG-62: lateral collapsible panels bar (v1.6.12)

The SESSIONI/GRAFO/COMPACTION/CoT chip row became a lateral, collapsible bar:
a freccetta expands it into a nav column plus the selected panel, so the
transcript is never pushed down."
echo "--- sparkforge ---"
git -C /home/jagones/Repositories/sparkforge log --oneline -n 2
echo "--- sparkpulse-app ---"
git -C /home/jagones/Repositories/sparkpulse-app log --oneline -n 2
