#!/bin/bash
cd /home/jagones/Repositories/sparkforge
git add server.py context_engine.py
cat > /tmp/jag66msg <<'MSGEOF'
JAG-66: context budget = the model's REAL context window (not hardcoded 6000)

/6000 was a fixed default, so the harness compacted even trivial conversations
while 131k/256k of context sat unused. The budget is now derived from the router:
meta.n_ctx (or --ctx-size) of the requested/loaded model, minus a reply reserve
(SPARKFORGE_CONTEXT_RESERVE, default 4096). An explicit SPARKFORGE_CONTEXT_BUDGET
still wins (used by tests). context_engine.DEFAULT_BUDGET fallback 6000 -> 32768.
router_models() now carries n_ctx; new model_context_window()/context_budget().

Evidence: GET /api/context -> budget_tokens 258048 (= 262144 - 4096).
Acceptance: tests/v06_taskgraph.py 16/16.
MSGEOF
git commit -F /tmp/jag66msg
git log -1 --oneline
