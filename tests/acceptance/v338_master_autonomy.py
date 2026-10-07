#!/usr/bin/env python3
"""v338 — the master may use tools/skills and author its OWN plan (JAG-338).

Item 1 (user): "master can use skills and tools and PLAN in its own chat, even deciding
the subtasks for the agents reporting to it". Historically the coordinator's
decomposition turn was told "do NOT call any tool; do NOT spawn subagents", and job
turns are never auto-planned (JAG-308) — so the harness had to seed the master's plan
(JAG-333). Now the coordinator MAY use tools/skills and write its own todos; the seed
is only a FALLBACK (it must not duplicate a plan the master authored).

Deterministic, no model. Run: python3 tests/acceptance/v338_master_autonomy.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-338-")
os.environ["SPARKFORGE_SESSIONS_DIR"] = os.path.join(TMP, "sessions")
os.environ["SPARKFORGE_GRAPH_DIR"] = os.path.join(TMP, "graphs")
os.environ["SPARKFORGE_DB"] = os.path.join(TMP, "events.db")
os.environ["SPARKFORGE_AGENTS_FILE"] = os.path.join(TMP, "agents.json")
os.environ["SPARKFORGE_JOBS_FILE"] = os.path.join(TMP, "jobs.json")
os.environ["SPARKFORGE_TEAMS_FILE"] = os.path.join(TMP, "teams.json")
os.makedirs(os.environ["SPARKFORGE_SESSIONS_DIR"], exist_ok=True)
os.makedirs(os.environ["SPARKFORGE_GRAPH_DIR"], exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from sparkforge import jobs, taskgraph as tg, server  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


JOB_SRC = open(os.path.join(REPO, "src", "sparkforge", "jobs.py"), encoding="utf-8").read()

# --- A: the coordinator prompt grants tools/skills + a plan -----------------
check("A1 the coordinator is allowed to plan", "Plan the work and decompose" in JOB_SRC)
check("A2 it may use tools and skills", "You MAY use your tools and skills" in JOB_SRC)
check("A3 it SHOULD record its own task list", "record your plan in your own task list" in JOB_SRC)
check("A4 the old blanket tool ban is gone", "do NOT call any tool" not in JOB_SRC)
check("A5 subagents are still forbidden", "do NOT spawn subagents" in JOB_SRC)
check("A6 it must still not do the teammates' work", "do NOT do the teammates' work yourself" in JOB_SRC)

# --- B: the harness plan seed is only a FALLBACK ---------------------------
check("B1 the seeder checks for an existing plan",
      "if tg.plan_nodes(g):" in JOB_SRC and "master planned itself" in JOB_SRC)

server.get_or_create_session("csess", "Master")
g = tg.ensure("csess", session_id="csess", goal="J9")
tg.add_node(g, "the master's own step", source="agent")   # master planned itself
tg.save(g)
before = len(tg.plan_nodes(tg.load("csess") or {}))

subs = jobs.plan_subjobs("J9", ["A1", "A2"], None, "- A2: do a thing", {})
jobs.JOBS._seed_coordinator_plan("csess", "J9", subs, {})
after = len(tg.plan_nodes(tg.load("csess") or {}))
check("B2 the seed does NOT duplicate a master-authored plan", after == before,
      "before=%d after=%d" % (before, after))

# an UNPLANNED coordinator still gets the seeded fallback
server.get_or_create_session("csess2", "Master2")
jobs.JOBS._seed_coordinator_plan("csess2", "J9", subs, {})
n = len(tg.plan_nodes(tg.load("csess2") or {}))
check("B3 an unplanned master still gets the seeded plan", n == len(subs), "n=%d" % n)

print("---")
ok = sum(1 for r in results if r)
print("%d/%d PASS" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)
