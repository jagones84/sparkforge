#!/usr/bin/env python3
"""v339 — TEAMS: a real group of agents, multi-team membership (JAG-339).

Item 4 (user): add one level above Agent — a TEAM, a group of agents (id TN). An agent
may belong to SEVERAL teams (decided: multiple teams now). The registry OWNS membership
(`team.members`); agents.py only reads it, so the two stores cannot drift.

Deterministic, no model. Run: python3 tests/acceptance/v339_teams.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-339-")
os.environ["SPARKFORGE_AGENTS_FILE"] = os.path.join(TMP, "agents.json")
os.environ["SPARKFORGE_TEAMS_FILE"] = os.path.join(TMP, "teams.json")
os.environ["SPARKFORGE_JOBS_FILE"] = os.path.join(TMP, "jobs.json")
os.environ["SPARKFORGE_DB"] = os.path.join(TMP, "events.db")
sys.path.insert(0, os.path.join(REPO, "src"))

from sparkforge import agents, teams, orchestration  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


class FakeHandler:
    def __init__(self):
        self.sent = None

    def _send(self, code, obj, ctype=None):
        self.sent = {"code": code, "obj": obj}
        return True


T = teams.REGISTRY

# --- A: CRUD ----------------------------------------------------------------
t1 = T.create("Startup MVP")
check("A1 a team gets a TN id", t1["ok"] and t1["team"]["id"] == "T1", str(t1.get("team", {}).get("id")))
check("A2 a team has a symbol + colour by default",
      bool(t1["team"]["symbol"]) and bool(t1["team"]["color"]))
t2 = T.create("Marketing")
t3 = T.create("Incident Response")
check("A3 team ids increment", [t2["team"]["id"], t3["team"]["id"]] == ["T2", "T3"])
check("A4 a duplicate name is refused", T.create("startup mvp")["ok"] is False)
check("A5 lookup by name works", (T.get("Marketing") or {}).get("id") == "T2")
T.update("T2", symbol="\U0001f4e3", color="#F97316")
check("A6 update changes symbol/colour", (T.get("T2") or {}).get("symbol") == "\U0001f4e3")

# --- B: multi-team membership ----------------------------------------------
a1 = agents.REGISTRY.designate("s1", name="CEO")["agent"]
a2 = agents.REGISTRY.designate("s2", name="Dev", reports_to="s1")["agent"]
T.add_member("T1", a1["id"])
T.add_member("T1", a2["id"])
T.add_member("T2", a1["id"])          # the SAME agent in two teams
check("B1 an agent can be in several teams", sorted(T.teams_of(a1["id"])) == ["T1", "T2"])
check("B2 membership is idempotent", (T.add_member("T1", a1["id"])["team"]["members"].count(a1["id"])) == 1)
check("B3 members_of lists the agent ids", sorted(T.members_of("T1")) == sorted([a1["id"], a2["id"]]))
check("B4 remove_member drops one link only",
      T.remove_member("T2", a1["id"])["ok"] and T.teams_of(a1["id"]) == ["T1"])
T.add_member("T2", a1["id"])

# --- C: agents expose their teams ------------------------------------------
lst = {a["id"]: a for a in agents.REGISTRY.list()["agents"]}
check("C1 GET agents carry `teams`", sorted(lst[a1["id"]]["teams"]) == ["T1", "T2"])
tree = agents.REGISTRY.tree()
check("C2 the org tree carries `teams` too",
      sorted({a["id"]: a for a in tree["agents"]}[a1["id"]]["teams"]) == ["T1", "T2"])
check("C3 agents_of_team returns member records",
      sorted(a["id"] for a in agents.REGISTRY.agents_of_team("T1")) == sorted([a1["id"], a2["id"]]))

# --- D: releasing an agent leaves every team -------------------------------
agents.REGISTRY.release("s2")
check("D1 a released agent is gone from its team", T.members_of("T1") == [a1["id"]])

# --- E: the API surface -----------------------------------------------------
fh = FakeHandler()
orchestration.handle(fh, "GET", "/api/teams", {}, None)
check("E1 GET /api/teams lists teams", fh.sent["code"] == 200 and fh.sent["obj"]["count"] == 3)
check("E2 a team payload carries resolved member rows",
      all("member_rows" in t for t in fh.sent["obj"]["teams"]))

fh = FakeHandler()
orchestration.handle(fh, "POST", "/api/teams", {}, {"name": "Support", "symbol": "S"})
check("E3 POST /api/teams creates", fh.sent["obj"]["ok"] and fh.sent["obj"]["team"]["id"] == "T4")

fh = FakeHandler()
orchestration.handle(fh, "POST", "/api/teams/T4/members", {}, {"agent": a2["id"], "action": "add"})
check("E4 POST members adds by agent id", fh.sent["obj"]["ok"] and a2["id"] in T.members_of("T4"))

fh = FakeHandler()
orchestration.handle(fh, "GET", "/api/teams/T1", {}, None)
check("E5 GET /api/teams/<id> returns detail + agents",
      fh.sent["code"] == 200 and "agents" in fh.sent["obj"])

fh = FakeHandler()
orchestration.handle(fh, "DELETE", "/api/teams/T4", {}, None)
check("E6 DELETE /api/teams/<id> removes it", fh.sent["obj"]["ok"] and T.get("T4") is None)

fh = FakeHandler()
check("E7 a non-team path is not shadowed",
      orchestration.handle(fh, "GET", "/api/status", {}, None) is False)

# --- F: POST /api/agents accepts teams --------------------------------------
fh = FakeHandler()
orchestration.handle(fh, "POST", "/api/agents", {}, {"session": "s9", "name": "Joined", "teams": ["T1"]})
joined = agents.REGISTRY.get("s9")
check("F1 designate can attach teams in one call",
      joined is not None and "T1" in T.teams_of(joined["id"]))

print("---")
ok = sum(1 for r in results if r)
print("%d/%d PASS" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)
