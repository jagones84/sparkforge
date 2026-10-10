#!/usr/bin/env python3
"""v289 — Job ops: reconcile after restart, re-run semantics, UI designate/retry.

A hard restart kills the in-process job worker, so a job left "running" must be
reconciled to "error" (mirrors reconcile_orphan_turns for sessions). Re-dispatching
a finished/failed job must clear the stale error. The Orbit UI must be able to
designate an agent and to re-run a job.

Deterministic (the worker is stubbed), no live model.
Run: python3 tests/v289_job_ops.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "src"))
TMP = tempfile.mkdtemp(prefix="sf-v289-")
os.environ["LONGRUN_JOBS_FILE"] = os.path.join(TMP, "jobs.json")
os.environ["LONGRUN_AGENTS_FILE"] = os.path.join(TMP, "agents.json")

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


from longrun import jobs  # noqa: E402

reg = jobs.JOBS
reg._run = lambda jid: None  # never spawn a real worker

made = reg.create("ship it", coordinator="A1", agents=["A1", "A2"])
jid = made["job"]["id"]
check("a job is created", made["ok"] and jid == "J1")

# --- reconcile a job left running by a hard restart -------------------------
reg._update(jid, lambda j: j.update({"status": "running"}))
n = reg.reconcile()
check("reconcile closes the running job", n == 1 and reg.get(jid)["status"] == "error")
check("reconcile records an interrupted reason", "interrupt" in (reg.get(jid).get("error") or ""))
check("reconcile leaves finished jobs alone", reg.reconcile() == 0)

# --- re-run semantics -------------------------------------------------------
res = reg.dispatch(jid)
check("dispatch re-runs a failed job", res["ok"] and reg.get(jid)["status"] == "running")
check("dispatch clears the stale error", (reg.get(jid).get("error") or "") == "")
check("dispatch refuses a job already running", reg.dispatch(jid)["ok"] is False)

# --- UI wiring --------------------------------------------------------------
with open(os.path.join(REPO, "src", "longrun", "orbit", "web", "orbit.html"), encoding="utf-8") as f:
    ui = f.read()
check("the Orbit UI can create + designate an agent",
      'id="agNew"' in ui and "async create()" in ui and '"/api/agents"' in ui
      and '"/api/orbit/sessions"' in ui)
check("the Orbit UI can re-run a finished/failed job", 'j.status !== "running"' in ui)

print("---")
passed = sum(results)
print("%d/%d PASS" % (passed, len(results)))
sys.exit(0 if passed == len(results) else 1)
