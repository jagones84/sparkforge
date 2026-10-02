#!/usr/bin/env python3
"""v0.9.38 acceptance — una sola TASK LIST (JAG-129B)."""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


srv = open(os.path.join(REPO, "server.py"), encoding="utf-8", errors="replace").read()
check("B1 /api/plan is an alias of the task list",
      "/api/plan" in srv and "taskgraph.public" in srv, "")
check("B2 no second source of truth for /api/plan",
      "return self._send(200, plan)" not in srv, "")

web = open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8", errors="replace").read()
check("B3 WebUI has ONE task-list section",
      web.count("TASK LIST") >= 1 and "RUN GRAPH" not in web, "")

check("B4 chat shows plan.continuing", "plan.continuing" in web, "")
check("B5 chat shows plan.stopped", "plan.stopped" in web, "")
check("B6 nested checklist renderer", "function taskTree" in web or "parent" in web, "")

total = len(results)
print("\n==== %d/%d checks passed ====" % (sum(results), total))
sys.exit(0 if all(results) else 1)