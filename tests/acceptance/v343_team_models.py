#!/usr/bin/env python3
"""v343 — team model policy: ≤1 local per machine, cheap cloud elsewhere, leads best (JAG-343).

Requested (user): "a team cannot have more than ONE local model per machine (dgx and
win); use cheap cloud models for the others; the strongest (but still cheap) cloud
models to the bosses." Applied via an Orbit button AND a guard on every model set.

Locked:
  * machine_of classifies a ref as a local machine (dgx/win) or cloud;
  * assign_models: leads -> LEAD cloud, others -> cheap cloud, at most ONE local kept
    per machine among the non-leads (leads never hold a local);
  * local_conflict finds a second local on the same machine within a shared team;
  * the API refuses a second local on POST /api/agents and exposes
    POST /api/teams/<id>/models.

Deterministic, no model. Run: python3 tests/acceptance/v343_team_models.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-343-")
os.environ["SPARKFORGE_AGENTS_FILE"] = os.path.join(TMP, "agents.json")
os.environ["SPARKFORGE_TEAMS_FILE"] = os.path.join(TMP, "teams.json")
os.environ["SPARKFORGE_JOBS_FILE"] = os.path.join(TMP, "jobs.json")
os.environ["SPARKFORGE_SESSIONS_DIR"] = os.path.join(TMP, "sessions")
os.environ["SPARKFORGE_GRAPH_DIR"] = os.path.join(TMP, "graphs")
os.environ["SPARKFORGE_DB"] = os.path.join(TMP, "events.db")
os.makedirs(os.environ["SPARKFORGE_SESSIONS_DIR"], exist_ok=True)
os.makedirs(os.environ["SPARKFORGE_GRAPH_DIR"], exist_ok=True)
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

# --- A: machine classification ---------------------------------------------
check("A1 no model -> the default LOCAL machine", teams.machine_of(None) == "dgx")
check("A2 dgx:<m> is local", teams.machine_of("dgx:glm-5.3-flash-iq2") == "dgx")
check("A3 win:<m> is local", teams.machine_of("win:gpt-oss-20b") == "win")
check("A4 an openrouter ref is cloud", teams.machine_of("openrouter:z-ai/glm-5.3-flash") is None)
check("A5 the deepseek API is cloud", teams.machine_of("deepseek:deepseek-chat") is None)

# --- B: organigram: root + lead + 2 specialists, all default (local today) --
T.create("Crew")
for sid, nm, rep in (("s1", "Coord", None), ("s2", "Lead", "s1"),
                     ("s3", "Spec A", "s2"), ("s4", "Spec B", "s2")):
    a = agents.REGISTRY.designate(sid, name=nm, reports_to=rep)["agent"]
    T.add_member("T1", a["id"])

res = T.assign_models("T1")
by = {a["name"]: a for a in agents.REGISTRY.list()["agents"]}
check("B1 the coordinator gets the strong cheap cloud", by["Coord"].get("model") == teams.LEAD_MODEL,
      str(by["Coord"].get("model")))
check("B2 a group lead gets the strong cheap cloud", by["Lead"].get("model") == teams.LEAD_MODEL)
specs = [by["Spec A"], by["Spec B"]]
check("B3 non-leads move to the cheap cloud model (except the one local kept)",
      sum(1 for s in specs if s.get("model") == teams.MEMBER_MODEL) == 1,
      str([s.get("model") for s in specs]))
check("B4 exactly ONE local stays per machine", len(res["local_kept"]) == 1, str(res["local_kept"]))
check("B5 no LEAD holds a local model", bool(by["Coord"].get("model")) and bool(by["Lead"].get("model")))
check("B6 assigned count is right (3 of 4 members)", res["assigned"] == 3, str(res["assigned"]))

# --- C: the guard ----------------------------------------------------------
keeper = next(s for s in specs if s["id"] in res["local_kept"])
clash = T.local_conflict(by["Spec B"]["id"], "dgx:qwen-3.8-27b-uncensored-q8")
check("C1 a 2nd local on the same machine is a conflict", clash is not None and clash["other"] == keeper["id"],
      str(clash))
check("C2 a cloud model never conflicts",
      T.local_conflict(by["Spec B"]["id"], teams.MEMBER_MODEL) is None)

T.create("Other")
o = agents.REGISTRY.designate("s9", name="Outsider")["agent"]
T.add_member("T2", o["id"])
check("C3 a local in ANOTHER team does not conflict",
      T.local_conflict(o["id"], "win:gpt-oss-20b") is None)

# --- D: the API ------------------------------------------------------------
fh = FakeHandler()
orchestration.handle(fh, "POST", "/api/teams/T1/models", {}, {})
check("D1 POST /api/teams/<id>/models applies the policy",
      fh.sent["code"] == 200 and fh.sent["obj"]["ok"], str(fh.sent["obj"]))

# make Spec B local again, then the guard must refuse a second local for the crew
T.set_members("T1", [by["Coord"]["id"], by["Lead"]["id"], by["Spec A"]["id"], by["Spec B"]["id"]])
agents.REGISTRY.set_model("s3", "dgx:glm-5.3-flash-iq2")
fh = FakeHandler()
orchestration.handle(fh, "POST", "/api/agents", {}, {"session": "s4", "model": "dgx:glm-5.3-flash-iq2"})
check("D2 the guard REFUSES a 2nd local per machine",
      fh.sent["obj"]["ok"] is False and "local model" in fh.sent["obj"]["error"],
      str(fh.sent["obj"].get("error")))
fh = FakeHandler()
orchestration.handle(fh, "POST", "/api/agents", {}, {"session": "s4", "model": teams.MEMBER_MODEL})
check("D3 a cloud model is allowed", fh.sent["obj"]["ok"] is True)

# --- E: env can change the cap ---------------------------------------------
os.environ["SPARKFORGE_TEAM_LOCAL_SLOTS"] = "0"
res0 = T.assign_models("T1")
check("E1 local_slots=0 keeps NO local",
      res0["local_kept"] == [] and all(
          (a.get("model") or "") for a in agents.REGISTRY.list()["agents"] if a["name"].startswith("Spec")))
os.environ.pop("SPARKFORGE_TEAM_LOCAL_SLOTS", None)

print("---")
ok = sum(1 for r in results if r)
print("%d/%d PASS" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)
