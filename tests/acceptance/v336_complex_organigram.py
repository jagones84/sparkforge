#!/usr/bin/env python3
"""v336 — a COMPLEX organigram job: the dependency DAG is deterministic (JAG-336).

Builds a small "S.p.A." org (CEO -> C-suite -> leads -> devs, Agency-Agents-style
profiles) and a COMPLEX dependency job over it, then asserts the wave scheduler
honours every edge, the subjobs carry the right deps, and nesting works. This is the
"much more complex agent suite" the dependency feature is meant for; it runs in the
standard battery.

Deterministic, no model. Run: python3 tests/acceptance/v336_complex_organigram.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-336-")
os.environ["LONGRUN_JOBS_FILE"] = os.path.join(TMP, "jobs.json")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.orchestrate.jobs import merge_deps, parse_plan_deps, plan_subjobs, waves  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


# ---- the org: a synthetic "S.p.A." (profiles in the spirit of Agency-Agents) ----
ORG = {
    "A1": "CEO", "A2": "CTO", "A3": "CFO", "A4": "COO",
    "A5": "Backend lead", "A6": "Frontend lead", "A7": "Data lead",
    "A8": "Backend dev 1", "A9": "Backend dev 2",
    "A10": "Frontend dev 1", "A11": "Frontend dev 2", "A12": "Data analyst",
}
# complex dependencies: C-suite waits on the CEO; leads on their exec; devs on leads.
DEPS = {
    "A2": ["A1"], "A3": ["A1"], "A4": ["A1"],
    "A5": ["A2"], "A6": ["A2"], "A7": ["A3"],
    "A8": ["A5"], "A9": ["A5"], "A10": ["A6"], "A11": ["A6"], "A12": ["A7", "A3"],
}
AGENTS = list(ORG)   # roster order is irrelevant; the DAG decides

W = waves(AGENTS, DEPS)


def wave_of(aid, w=None):
    w = w if w is not None else W
    return next(i for i, x in enumerate(w) if aid in x)


check("A1 the CEO runs first, alone", W[0] == ["A1"], str(W))
check("A2 the C-suite runs together once the CEO is done",
      set(W[1]) == {"A2", "A3", "A4"}, str(W))
check("A3 EVERY dependency runs in a strictly earlier wave",
      all(wave_of(a) < wave_of(k) for k, ds in DEPS.items() for a in ds), str(W))
check("A4 all 12 agents are scheduled exactly once",
      sorted(a for wave in W for a in wave) == sorted(AGENTS))
check("A5 a two-parent node (A12) waits for BOTH parents",
      wave_of("A12") > wave_of("A7") and wave_of("A12") > wave_of("A3"), str(W))

# ---- the job becomes subjobs over the SAME DAG -------------------------------
PLAN = "\n".join("- %s: do the work (after %s)" % (a, ", ".join(DEPS[a]))
                 for a in AGENTS if a in DEPS)
check("B0 the coordinator's declared deps are read back", parse_plan_deps(PLAN) == DEPS)

deps = merge_deps({}, parse_plan_deps(PLAN))
subs = plan_subjobs("J9", AGENTS, "A1", PLAN, deps)
by_agent = {s["agent"]: s for s in subs.values()}

check("B1 the CEO (coordinator) is NOT a subjob", "A1" not in by_agent)
check("B2 11 subjobs for the 11 members", len(subs) == 11, str(len(subs)))
check("B3 the C-suite subjobs have no subjob dep (their parent is the CEO, filtered)",
      all(by_agent[x]["deps"] == [] for x in ("A2", "A3", "A4")))
check("B4 a lead's subjob depends on its exec's subjob",
      by_agent["A5"]["deps"] == [by_agent["A2"]["id"]], str(by_agent["A5"]["deps"]))
check("B5 a dev's subjob depends on its lead's subjob",
      by_agent["A8"]["deps"] == [by_agent["A5"]["id"]])
check("B6 A12's subjob depends on BOTH parents' subjobs",
      sorted(by_agent["A12"]["deps"]) == sorted([by_agent["A7"]["id"], by_agent["A3"]["id"]]),
      str(by_agent["A12"]["deps"]))
check("B7 subjob ids are J9.j and bound to one agent each",
      set(subs) == {"J9.%d" % i for i in range(1, 12)}, str(sorted(subs)))

# ---- one deeper level: a subjob handed out from INSIDE a subjob --------------
nested = plan_subjobs("J9", ["A8", "A9"], None, "", {"A9": ["A8"]}, parent_sub=by_agent["A5"]["id"])
check("C1 nested subjobs nest under the parent subjob id",
      set(nested) == {by_agent["A5"]["id"] + ".1", by_agent["A5"]["id"] + ".2"},
      str(sorted(nested)))
check("C2 a nested dep points at the nested id",
      nested[by_agent["A5"]["id"] + ".2"]["deps"] == [by_agent["A5"]["id"] + ".1"])

print("---")
ok = sum(1 for r in results if r)
print("%d/%d PASS" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)

