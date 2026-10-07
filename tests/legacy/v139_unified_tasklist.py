#!/usr/bin/env python3
"""v0.9.38 acceptance — una sola TASK LIST (JAG-129B)."""
import os
import re as _re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "src"))
results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


srv = open(os.path.join(REPO, "src", "sparkforge", "server.py"), encoding="utf-8", errors="replace").read()
check("B1 /api/plan is an alias of the task list",
      "/api/plan" in srv and "taskgraph.public" in srv, "")
check("B2 no second source of truth for /api/plan",
      "return self._send(200, plan)" not in srv, "")

web = open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8", errors="replace").read()
check("B3 WebUI has ONE task-list section",
      web.count("TASK LIST") >= 1 and "RUN GRAPH" not in web, "")

sse_block = web[web.index("new EventSource(url)"):web.index('es.addEventListener("error"')]
check("B4 chat SSE wires plan.continuing to planContinuing",
      "plan.continuing" in sse_block and "planContinuing(" in sse_block, "")
check("B5 chat SSE wires plan.stopped to planStopped",
      "plan.stopped" in sse_block and "planStopped(" in sse_block, "")
check("B6 nested renderer is actually wired",
      bool(_re.search(r"taskTree\s*\(", web)) and "function taskTree" in web
      and web.count("taskTree(") >= 2, "")
tt = web.split("function taskTree", 1)[1].split("function", 1)[0]
check("B7 taskTree parks orphans under root and guards cycles",
      "ids.has(n.parent)" in tt and "seen.has(" in tt and "!seen.has(" in tt, "")

total = len(results)
print("\n==== %d/%d checks passed ====" % (sum(results), total))
sys.exit(0 if all(results) else 1)