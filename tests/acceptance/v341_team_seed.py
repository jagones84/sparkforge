#!/usr/bin/env python3
"""v341 — seed 3 diversified TEAMS with organigrams from agency-agents (JAG-339).

Item 5 (user): "make 3 diversified teams each with an organigram from agency-agents".
The seeder reads a runbook roster and materialises one team whose members form an
organigram (coordinator -> group lead -> specialists). This test drives it against a
SYNTHETIC agency fixture (no network, deterministic) and locks:
  * 3 teams created, one per runbook;
  * the organigram: a specialist reports_to its group lead, the lead to the root;
  * idempotency: a second run creates no new agents.

Run: python3 tests/acceptance/v341_team_seed.py
"""
import json
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-341-")
AGENCY = os.path.join(TMP, "agency")
os.makedirs(os.path.join(AGENCY, "engineering"), exist_ok=True)
os.makedirs(os.path.join(AGENCY, "strategy"), exist_ok=True)

# --- synthetic agency fixture ----------------------------------------------
RUNBOOKS = {"runbooks": []}
AGENT_MD = {
    "eng-root": "Alpha Root", "eng-a": "Alpha Engineer",
    "mkt-a": "Alpha Marketing Lead", "mkt-b": "Alpha Marketer",
    "beta-root": "Beta Root", "beta-eng": "Beta Engineer",
    "ops-a": "Ops Lead", "ops-b": "Ops Analyst",
    "gamma-root": "Gamma Root", "gamma-qa": "Gamma QA", "gamma-doc": "Gamma Writer",
}
for slug, disp in AGENT_MD.items():
    with open(os.path.join(AGENCY, "engineering", slug + ".md"), "w", encoding="utf-8") as f:
        f.write("---\nname: %s\ndescription: expert at %s\nemoji: \U0001f9ea\n---\n\n# %s\n"
                % (disp, disp, disp))

def _rb(slug, title, groups):
    RUNBOOKS["runbooks"].append({"slug": slug, "title": title, "summary": title + " summary",
                                 "roster": [{"group": g, "agents": a} for g, a in groups]})

_rb("alpha", "Alpha Team", [("Core", ["eng-root", "eng-a"]), ("Growth", ["mkt-a", "mkt-b"])])
_rb("beta", "Beta Team", [("Core", ["beta-root", "beta-eng"]), ("Ops", ["ops-a", "ops-b"])])
_rb("gamma", "Gamma Team", [("Core", ["gamma-root", "gamma-qa", "gamma-doc"])])

with open(os.path.join(AGENCY, "strategy", "runbooks.json"), "w", encoding="utf-8") as f:
    json.dump(RUNBOOKS, f)

# --- isolate the harness stores, then import the seeder ---------------------
os.environ["LONGRUN_AGENCY_DIR"] = AGENCY
os.environ["LONGRUN_AGENTS_FILE"] = os.path.join(TMP, "agents.json")
os.environ["LONGRUN_TEAMS_FILE"] = os.path.join(TMP, "teams.json")
os.environ["LONGRUN_JOBS_FILE"] = os.path.join(TMP, "jobs.json")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(TMP, "sessions")
os.environ["LONGRUN_GRAPH_DIR"] = os.path.join(TMP, "graphs")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
os.environ["LONGRUN_ROLES_DIR"] = os.path.join(TMP, "roles")
os.makedirs(os.environ["LONGRUN_SESSIONS_DIR"], exist_ok=True)
os.makedirs(os.environ["LONGRUN_GRAPH_DIR"], exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))
sys.path.insert(0, os.path.join(REPO, "scripts"))

import seed_teams  # noqa: E402
from longrun import agents, teams, roles, agency  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


res = seed_teams.seed(["alpha", "beta", "gamma"])
check("N1 three teams are created", len(res["teams"]) == 3, str(res["teams"]))
check("N2 every roster slug resolved (none missing)", res["missing"] == [], str(res["missing"]))

tl = teams.REGISTRY.list()["teams"]
check("N3 team ids are T1..T3", [t["id"] for t in tl] == ["T1", "T2", "T3"])
check("N4 each team has members", all(t["members"] for t in tl))

by_name = {a["name"]: a for a in agents.REGISTRY.list()["agents"]}
root, eng, lead, marketer = (by_name.get("Alpha Root"), by_name.get("Alpha Engineer"),
                             by_name.get("Alpha Marketing Lead"), by_name.get("Alpha Marketer"))
check("O1 a Core specialist reports_to the root",
      root and eng and eng["reports_to"] == root["id"])
check("O2 a group lead reports_to the root",
      root and lead and lead["reports_to"] == root["id"])
check("O3 a specialist reports_to its group lead",
      lead and marketer and marketer["reports_to"] == lead["id"])
check("O4 the members carry the team", tl[0]["id"] in (eng.get("teams") or []))

res2 = seed_teams.seed(["alpha", "beta", "gamma"])
check("P1 re-running is idempotent (no new agents)", res2["agents_created"] == 0,
      "created=%d" % res2["agents_created"])
check("P2 re-running keeps the same teams", len(teams.REGISTRY.list()["teams"]) == 3)

# --- Q: the agent ROLE.md is materialised from the clone (JAG-365) -----------
eng_role = roles.read(eng["session"])
check("Q1 the seeder wrote the agent's ROLE.md from the clone body",
      eng_role.strip().startswith("# Alpha Engineer"), eng_role[:44].replace("\n", " "))
check("Q2 every seeded agent matched a clone agent (roles filled, none unmatched)",
      res["roles"]["filled"] and not res["roles"]["unmatched"]
      and not res["roles"]["failed"], str(res["roles"]))
check("Q3 the role the seeder wrote IS what both UIs read (same file)",
      roles.read(eng["session"]) == agency.role_for("Alpha Engineer"), "")
roles.write(eng["session"], "MY CUSTOM ROLE")
res3 = seed_teams.seed(["alpha"])
check("Q4 a user-written role is NOT clobbered on a re-seed",
      roles.read(eng["session"]) == "MY CUSTOM ROLE", str(res3["roles"].get("kept")))

print("---")
ok = sum(1 for r in results if r)
print("%d/%d PASS" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)
