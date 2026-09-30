#!/bin/bash
set -e
cd /home/jagones/Repositories/sparkforge
git add server.py tests/v06_taskgraph.py
cat > /tmp/m1 <<'EOF'
JAG-64: never leak raw tool-call JSON into chat + test isolation

- server: _looks_like_json_action() catches malformed/TRUNCATED tool-call JSON
  (extract_json fails, so the raw text used to be shown as the reply). It now
  nudges the model for a valid call or plain prose, plus a last-resort guard
  before the assistant turn is persisted.
- tests/v06_taskgraph: use a fresh session per run (the task list is keyed by
  session and persists, so checks must not reuse a session). 16/16 pass.
EOF
git commit -F /tmp/m1 >/dev/null
cd /home/jagones/Repositories/sparkpulse-app
git add app/src/main/java/com/jagones/sparkpulse/ForgeScreen.kt app/build.gradle.kts
cat > /tmp/m2 <<'EOF'
JAG-64: pin the panels bar so it never scrolls away (v1.6.13)

The PANNELLI rail lived inside the scrolling column, so it scrolled out of view
and seemed to disappear. It is now pinned under the header and always visible;
the freccetta collapses only the panel content, never the bar itself.
EOF
git commit -F /tmp/m2 >/dev/null
echo "--- sparkforge ---"
git -C /home/jagones/Repositories/sparkforge log --oneline -n 3
echo "--- sparkpulse-app ---"
git -C /home/jagones/Repositories/sparkpulse-app log --oneline -n 3
rm -f /tmp/m1 /tmp/m2
