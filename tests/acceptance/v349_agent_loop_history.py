#!/usr/bin/env python3
"""v349 — the agent loop must see its OWN previous steps (no open loop).

Open loop found by the loop audit: `/api/agent/run` (server.agent_run) rebuilt its
messages from scratch EVERY iteration and injected only the task list — never the
previous action's observation. So the model could not use a subagent's result,
could not correct a rejected action ("unknown action"/"task not found"), and
re-derived the same step each iteration. That is the exact failure JAG-61 fixed in
the chat loop; the agent loop never got it.

Deterministic, no model. Run: python3 tests/acceptance/v349_agent_loop_history.py
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "src"))

from sparkforge import server  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


# --- A: the history renders action -> observation, newest kept ---------------
h = server._agent_history([
    {"i": 1, "action": "note", "observation": "noted"},
    {"i": 2, "action": "subagent", "observation": "subagent spawned: A3 (goal: probe)"},
    {"i": 3, "action": "complete_task", "observation": "task not found"},
])
check("A1 the history is non-empty", bool(h.strip()), repr(h)[:120])
check("A2 it carries a subagent result", "subagent spawned: A3" in h, "")
check("A3 it carries a rejected action's observation", "task not found" in h, "")
check("A4 it is framed as the model's own previous steps",
      "previous steps" in h and "do NOT repeat" in h, "")

# --- B: empty history is empty (no stray block) ------------------------------
check("B1 no actions -> empty string", server._agent_history([]) == "", "")
check("B2 None is tolerated", server._agent_history(None) == "", "")

# --- C: bounded (never floods the context) -----------------------------------
big = [{"i": i, "action": "note", "observation": "x" * 500} for i in range(50)]
_rows = [ln for ln in server._agent_history(big, limit=8).splitlines() if ln.startswith("  ")]
check("C1 the history keeps only the most recent steps (8)", len(_rows) == 8, str(len(_rows)))
check("C2 a huge observation is truncated per row",
      max(len(ln) for ln in server._agent_history(big, limit=8).splitlines()) < 400, "")

# --- D: the LIVE loop actually uses it (source wiring) -----------------------
src = open(os.path.join(REPO, "src", "sparkforge", "server.py"), encoding="utf-8").read()
check("D1 _agent_history is defined", "def _agent_history(" in src, "")
check("D2 the agent-run user turn injects the history",
      "_agent_history(actions)" in src, "")

print("---")
ok = sum(results)
print("%d/%d PASS" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)
