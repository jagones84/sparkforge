#!/usr/bin/env python3
"""v0.9.38 acceptance — todo annidati per subagent (JAG-129C)."""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
os.environ["SPARKFORGE_GRAPH_DIR"] = tempfile.mkdtemp()
results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


import taskgraph  # noqa: E402

g = taskgraph.ensure("run_child1", session_id="run_child1", goal="child")
n = taskgraph.add_node(g, "subtask A", child_run_id="sub_123")
check("C1 node carries child_run_id", n.get("child_run_id") == "sub_123", str(n.get("child_run_id")))

child = taskgraph.ensure("sub_123", session_id="sub_123", goal="child goal")
taskgraph.apply_write_todos(child, [{"label": "passo figlio 1"}, {"label": "passo figlio 2"}])
check("C2 child has its own list", len(taskgraph.load("sub_123")["nodes"]) == 2, "")
check("C3 parent list is separate", len(taskgraph.load("run_child1")["nodes"]) == 1, "")

import keepgoing  # noqa: E402
import subagent  # noqa: E402
check("C4 depth limit enforced", subagent.depth_allowed(2, 2) is False, "")
check("C5 depth allowed below cap", subagent.depth_allowed(1, 2) is True, "")

total = len(results)
print("\n==== %d/%d checks passed ====" % (sum(results), total))
sys.exit(0 if all(results) else 1)