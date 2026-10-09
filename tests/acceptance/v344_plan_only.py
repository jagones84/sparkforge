#!/usr/bin/env python3
"""v344 — the coordinator's PLANNING turn is plan-only; assignments are specific (JAG-344).

Two live bugs this locks down:

1. The master COMPLETED THE WHOLE JOB ITSELF in its planning turn (it wrote the
   deliverable files and "verified" them) instead of decomposing — because the turn
   had the full tool budget AND the keepgoing continuation loop nagged it to close
   its own todos. A plan turn must stop after planning (`plan_only`).
2. Every subjob was handed the SAME assignment text: the plan carried an aggregate
   line ("critical path: A13 -> A14 -> A15") and `_assignment_for` returned the FIRST
   line containing the id — which matched for every agent.

Deterministic, no model. Run: python3 tests/acceptance/v344_plan_only.py
"""
import inspect
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-344-")
os.environ["SPARKFORGE_AGENTS_FILE"] = os.path.join(TMP, "agents.json")
os.environ["SPARKFORGE_TEAMS_FILE"] = os.path.join(TMP, "teams.json")
os.environ["SPARKFORGE_JOBS_FILE"] = os.path.join(TMP, "jobs.json")
os.environ["SPARKFORGE_SESSIONS_DIR"] = os.path.join(TMP, "sessions")
os.environ["SPARKFORGE_GRAPH_DIR"] = os.path.join(TMP, "graphs")
os.environ["SPARKFORGE_DB"] = os.path.join(TMP, "events.db")
os.makedirs(os.environ["SPARKFORGE_SESSIONS_DIR"], exist_ok=True)
os.makedirs(os.environ["SPARKFORGE_GRAPH_DIR"], exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src2"))
sys.path.insert(0, os.path.join(REPO, "src"))

from sparkforge import jobs, server  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


# --- 1. assignments are per-agent, not the aggregate line ------------------
PLAN = (
    "Plan for the kickoff package.\n"
    "Team assignments (critical path: A13 -> A14 -> A15 -> A16 -> A17):\n"
    "- A13 (requirements): write the requirements doc (after none)\n"
    "- A14 (ux): design the UX flow (after A13)\n"
    "- A15 (data): specify the data model (after A14)\n"
)
a13 = jobs.JobRegistry._assignment_for(PLAN, "A13")
a14 = jobs.JobRegistry._assignment_for(PLAN, "A14")
check("A1 the assignment is A13's OWN bullet, not the critical-path line",
      a13 == "- A13 (requirements): write the requirements doc (after none)", repr(a13))
check("A2 two agents get DIFFERENT assignments", a13 != a14, "%r vs %r" % (a13, a14))
check("A3 A14's assignment is its own bullet",
      a14 == "- A14 (ux): design the UX flow (after A13)", repr(a14))

# an agent NOT named in the plan still gets the whole plan (the fallback)
check("A4 an unnamed agent falls back to the whole plan",
      jobs.JobRegistry._assignment_for(PLAN, "A99") == PLAN.strip())

# the JAG-303 baseline: a single clean line is still returned verbatim
check("A5 a single bullet is returned as before",
      jobs.JobRegistry._assignment_for("- A5 (api): endpoints", "A5")
      == "- A5 (api): endpoints")


# --- 2. the plan-only turn is wired ----------------------------------------
check("B1 chat_once accepts plan_only",
      "plan_only" in inspect.signature(server.chat_once).parameters)
check("B2 chat_stream_gen accepts plan_only",
      "plan_only" in inspect.signature(server.chat_stream_gen).parameters)
check("B3 chat_once passes plan_only to the loop (signature default)",
      inspect.signature(server.chat_once).parameters["plan_only"].default is False)
check("B4 a plan-only turn caps the real-tool budget",
      hasattr(server, "PLAN_ONLY_MAX_STEPS") and int(server.PLAN_ONLY_MAX_STEPS) > 0)

srv_src = open(os.path.join(REPO, "src", "sparkforge", "server.py"), encoding="utf-8").read()
srv_src += open(os.path.join(REPO, "src", "sparkforge", "agent.py"), encoding="utf-8").read()
check("B5 the loop stops with a typed 'plan_only' reason",
      'reason="plan_only"' in srv_src and '_kg_stop_reason = "plan_only"' in srv_src)
check("B6 the plan_only stop precedes the keepgoing decide",
      srv_src.index('_kg_stop_reason = "plan_only"') < srv_src.index("_dec = _kg.decide("))

jobs_src = open(os.path.join(REPO, "src", "sparkforge", "jobs.py"), encoding="utf-8").read()
check("B7 the coordinator PLANNING turn is plan_only",
      'jid=jid, plan_only=True' in jobs_src)
check("B8 the coordinator is told to STOP after planning",
      "PLANNING ONLY" in jobs_src)
check("B9 _run_agent threads plan_only",
      "plan_only=plan_only" in jobs_src)

# --- 3. a plan-only turn is READ-ONLY --------------------------------------
check("C1 PLAN_ONLY_TOOLS is an inspection-only allowlist",
      hasattr(server, "PLAN_ONLY_TOOLS")
      and server.PLAN_ONLY_TOOLS == {"fs.read", "skills", "memory", "self"})
check("C2 no MUTATING tool is in the plan-only allowlist",
      "fs.write" not in server.PLAN_ONLY_TOOLS
      and "fs.edit" not in server.PLAN_ONLY_TOOLS
      and "shell" not in server.PLAN_ONLY_TOOLS
      and "subagent" not in server.PLAN_ONLY_TOOLS)
check("C3 the refusal directive exists and names the tools",
      callable(getattr(server, "_plan_only_refusal", None))
      and "PLAN-ONLY turn" in server._plan_only_refusal("fs.write"))
check("C4 a mutating tool call is refused in a plan-only turn",
      "plan_only and tool not in PLAN_ONLY_TOOLS" in srv_src
      and "_plan_only_refusal(tool)" in srv_src)
check("C5 spawning subagents is refused in a plan-only turn",
      "PLAN-ONLY turn: spawning subagents" in srv_src)

print("---")
passed = sum(results)
print("%d/%d PASS" % (passed, len(results)))
sys.exit(0 if passed == len(results) else 1)
