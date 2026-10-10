#!/usr/bin/env python3
"""v333 — the MASTER gets a visible PLAN (one todo per delegated subjob) (JAG-333).

Observed: the coordinator's panel showed NO plan. By design job turns are never
auto-planned (JAG-308) and the coordinator is told not to call tools, so nothing ever
created its task list. The harness now SEEDS it from the decomposition: one todo per
subjob, tagged with the subjob id, on the coordinator's own graph.

Deterministic, no model. Run: python3 tests/acceptance/v333_master_plan.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-333-")
os.environ["LONGRUN_JOBS_FILE"] = os.path.join(TMP, "jobs.json")
os.environ["LONGRUN_AGENTS_FILE"] = os.path.join(TMP, "agents.json")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(TMP, "sessions")
os.environ["LONGRUN_GRAPH_DIR"] = os.path.join(TMP, "graphs")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
os.makedirs(os.environ["LONGRUN_SESSIONS_DIR"], exist_ok=True)
os.makedirs(os.environ["LONGRUN_GRAPH_DIR"], exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.agent import agents  # noqa: E402
from longrun.orchestrate import jobs  # noqa: E402
from longrun.plan import taskgraph as tg  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


def read(*parts):
    with open(os.path.join(REPO, *parts), encoding="utf-8") as f:
        return f.read()


SID = "sessM"
agents.REGISTRY.designate(SID, name="Master")
AID = agents.REGISTRY.list()["agents"][0]["id"]
made = jobs.JOBS.create("seed plan goal", coordinator=AID, agents=[AID])
JID = made["job"]["id"]
subs = {
    JID + ".1": {"id": JID + ".1", "parent": JID, "agent": "A9", "deps": [],
                 "assignment": "scaffold", "status": "pending"},
    JID + ".2": {"id": JID + ".2", "parent": JID, "agent": "A11", "deps": [JID + ".1"],
                 "assignment": "deploy", "status": "pending"},
}
jobs.JobRegistry._scope_graph(SID, JID, "seed plan goal")
jobs.JOBS._seed_coordinator_plan(SID, JID, subs, {"A9": {"name": "coder 1"},
                                                  "A11": {"name": "coder 2"}})
g = tg.load(SID) or {}
nodes = g.get("nodes") or []
check("A1 the master now HAS a plan (nodes were seeded)", len(nodes) >= 2, "n=%d" % len(nodes))
by_sub = {n.get("subjob"): n for n in nodes}
check("A2 one todo per subjob, tagged with the subjob id",
      all(k in by_sub for k in subs), str(sorted(by_sub)))
check("A3 the todos carry the job id too (jid)", all(n.get("jid") == JID for n in nodes),
      str([n.get("jid") for n in nodes]))
check("A4 the node label names the subjob and the assignee",
      JID + ".1" in by_sub[JID + ".1"]["label"] and "A9" in by_sub[JID + ".1"]["label"],
      by_sub[JID + ".1"]["label"] if JID + ".1" in by_sub else "")

src = read("src", "longrun", "orchestrate/jobs.py")
check("B1 the runner seeds the master's plan after the delegation is announced",
      "self._seed_coordinator_plan(" in src)
check("B2 the seeder writes one node per subjob",
      "def _seed_coordinator_plan(self, coord_sid, jid, subs, roster)" in src)

print("---")
ok = sum(1 for r in results if r)
print("%d/%d PASS" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)

