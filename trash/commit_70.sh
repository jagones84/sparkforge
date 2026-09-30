#!/bin/bash
set -e
cd /home/jagones/Repositories/sparkforge
git add server.py tests/v074_context.py
cat > /tmp/jag70h <<'MSGEOF'
JAG-70: ctx indicator = the REAL prompt size + auto-compaction at 75%

The indicator's "x" was the stored transcript only: measured 191 tokens while
the request actually sent 3439 (~18x more), because the SYSTEM prompt dominates
(tool registry alone = 2621 tokens). It also had no auto-compaction trigger.

- `_system_prompt(sess)` is now the single assembler used by BOTH the model call
  and the indicator, so the measured size cannot drift from what is sent.
- `context_usage()`/`context_status()` return tokens_used = system + compacted
  transcript + pending message, plus system_tokens/transcript_tokens/pct.
- `AUTOCOMPACT_PCT` (SPARKFORGE_CONTEXT_AUTOCOMPACT_PCT, default 75): when the
  real prompt crosses the threshold the stored transcript is auto-compacted at
  the start of the turn (before the JAG-51 `since` boundary, extractive + local
  so it can never stall), emitting `context.auto_compact`.

Evidence: GET /api/context -> tokens_used 3278 (system 3087) instead of 191.
Acceptance: tests/v074_context.py 6/6; regression tests/v06_taskgraph.py 16/16.
MSGEOF
git commit -F /tmp/jag70h
git log -1 --oneline

cd /home/jagones/Repositories/sparkpulse-app
git add app/src/main/java/com/jagones/sparkpulse/ForgeScreen.kt \
        app/src/main/java/com/jagones/sparkpulse/ForgePanels.kt app/build.gradle.kts
cat > /tmp/jag70a <<'MSGEOF'
JAG-70: ctx shows the real prompt size + threshold

Indicator now shows `ctx 3.3k/258k · 1%` (compact "k" formatting), amber at the
auto-compaction threshold and coral over budget; the compact panel names the
threshold; `context.built` updates it live and `context.auto_compact` reports it.
v1.6.16 (versionCode 24). Build + install OK on oneplus-15r.
MSGEOF
git commit -F /tmp/jag70a
git log -1 --oneline
