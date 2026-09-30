#!/bin/bash
cd /home/jagones/Repositories/sparkforge
git add README.md
cat > /tmp/msgdocs <<'MSGEOF'
docs(README): hooks (JAG-69), stop-tool (JAG-68), inline task list (JAG-65), real ctx budget (JAG-66)
MSGEOF
git commit -F /tmp/msgdocs
git log -1 --oneline
echo "--- parent repo? ---"
git -C /home/jagones/Repositories rev-parse --is-inside-work-tree 2>&1 || true
git -C /home/jagones/Repositories status --short 2>&1 | head -n 10 || true
