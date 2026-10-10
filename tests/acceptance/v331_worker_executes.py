#!/usr/bin/env python3
"""v331 — a delegated subjob is WORK TO DO, not a paragraph to write (JAG-331).

SEVERE report: a worker (coder 2) replied with a PLAN and "this turn exposes no
callable shell/ADB or device tools" instead of deploying. Root cause: the delegation
message told it "Deliver ONLY your part as concise plain text now" — so the worker
narrated the task instead of executing it, even though the system prompt DOES carry
the tool registry and the skills index.

Fix: the delegation now tells the worker to DO the assignment end to end with its
tools and skills, then report the concrete RESULT.

Deterministic, no model. Run: python3 tests/acceptance/v331_worker_executes.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-331-")
os.environ["LONGRUN_JOBS_FILE"] = os.path.join(TMP, "jobs.json")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.jobs import JobRegistry  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


MSG = JobRegistry._delegation_msg(
    "J8", "A8 (Master)", {"id": "J8.2", "deps": ["J8.1"]}, "deploy the app", "- A11: deploy it")

check("A1 the worker is told to DO the work", "DO this now" in MSG)
check("A2 the worker is told it HAS tools", "You HAVE tools" in MSG)
check("A3 the worker is pointed at the skills tool",
      "skills" in MSG and "skills{action:'search'" in MSG)
check("A4 it is told NOT to just describe or refuse",
      "Do NOT merely describe" in MSG)
check("A5 the OLD 'plain text only' contract is gone",
      "concise plain text" not in MSG and "keep the reply short" not in MSG)
check("A6 the constraints are kept (no subagents, no other parts)",
      "do NOT spawn subagents" in MSG and "do NOT do the other agents' parts" in MSG)
check("A7 the declared dependency is still stated", "Waits for (already completed): J8.1." in MSG)

with open(os.path.join(REPO, "src", "longrun", "jobs.py"), encoding="utf-8") as f:
    src = f.read()
check("B1 the plain-text-only wording is gone from the source", "concise plain text" not in src)
check("B2 the delegation tells the worker to execute", "DO this now, end to end." in src)

print("---")
ok = sum(1 for r in results if r)
print("%d/%d PASS" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)
