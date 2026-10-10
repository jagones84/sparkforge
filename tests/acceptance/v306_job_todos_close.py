#!/usr/bin/env python3
"""v306 — a job must never leave a plan the harness created and nobody closes (JAG-308).

Root cause of "the job finished with OPEN todos" (found by tracing data/events.db):

  * JAG-194 (`chat_stream_gen` start): when the session graph is `all_done`, the
    turn starts a NEW, EMPTY plan.
  * JAG-76 (`chat_stream_gen` end): if the current plan has no steps, a BACKGROUND
    planner creates a plan FROM THE TURN'S MESSAGE.
  * JAG-173: the harness never auto-closes a step (closing without evidence would
    be lying) and JAG-295: a headless turn has no HITL gate.

Together, a completed job turn immediately got a fresh plan built out of its own
prompt (the coordinator's synthesis "Team results: ..." -> plan nodes n20..n25),
which no turn executes and nobody closes -> the job was marked `done` with OPEN
todos. The fix is NOT to force-close them (that was tried and rejected) but to
never create them: the fallback planner must not run for a JOB turn.

Locked here:
  * `_should_autoplan` is False whenever `jid` is set (a job turn);
  * it still runs for real interactive turns with an empty plan;
  * the fallback planner is gated on it;
  * the rejected external sweep (`_close_job_todos`) is gone.

Deterministic, no live model. Run: python3 tests/v306_job_todos_close.py
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "src"))
sys.path.insert(0, os.path.join(REPO, "src"))

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


def read(*parts):
    with open(os.path.join(REPO, *parts), encoding="utf-8") as f:
        return f.read()


from longrun.core import server  # noqa: E402
from longrun.plan import taskgraph as tg  # noqa: E402

LONG = "design a compact REST API for a personal library service with endpoints"

# --- the fallback planner must NEVER run for a job turn -------------------------
check("a job turn (jid set) is never auto-planned",
      server._should_autoplan("J2", None, True, LONG) is False)
check("a job turn is not auto-planned even with a long message",
      server._should_autoplan("J2", None, False, LONG) is False)

# --- but it still runs for real interactive turns ------------------------------
check("an interactive long message with an empty plan IS auto-planned",
      server._should_autoplan(None, None, False, LONG) is True)
check("an interactive autonomous turn with an empty plan IS auto-planned",
      server._should_autoplan(None, None, True, "hi") is True)
check("a one-line interactive greeting is NOT auto-planned",
      server._should_autoplan(None, None, False, "hi") is False)

# a plan that already has steps is never re-planned
SID = "v306ap"
g = tg.ensure(SID, session_id=SID, goal="x")
tg.add_node(g, "one step")
check("an existing plan with steps is not re-planned",
      server._should_autoplan(None, tg.load(SID), True, LONG) is False)

# ------------------------------------------------------------------ source locks
s = read("src", "longrun", "core/server.py") + read("src", "longrun", "core/httpapi.py")
check("the auto-plan gate exists", "def _should_autoplan(jid, graph, autonomous, message)" in s)
check("the fallback planner is gated on the gate",
      "_should_autoplan(jid, _g, autonomous, message)" in s)
check("the auto-planner no longer runs unguarded",
      "if (not _g or not taskgraph.plan_nodes(_g)) and \\\n" not in s)
check("plan.incomplete counts only TRULY-open steps (not superseded)",
      'not in ("done", "cancelled")' not in s)

j = read("src", "longrun", "orchestrate/jobs.py")
check("the rejected external sweep is gone",
      "def _close_job_todos" not in j and "todos_closed" not in j)

print("---")
passed = sum(results)
print("%d/%d PASS" % (passed, len(results)))
sys.exit(0 if passed == len(results) else 1)

