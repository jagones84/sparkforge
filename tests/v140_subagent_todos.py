#!/usr/bin/env python3
"""v0.9.38 acceptance — todo annidati per subagent (JAG-129C)."""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "src"))
import atexit  # noqa: E402
import shutil  # noqa: E402
_sf_tmp = tempfile.mkdtemp()
os.environ["SPARKFORGE_GRAPH_DIR"] = _sf_tmp
atexit.register(lambda: shutil.rmtree(_sf_tmp, ignore_errors=True))
results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


from sparkforge import taskgraph  # noqa: E402

g = taskgraph.ensure("run_child1", session_id="run_child1", goal="child")
n = taskgraph.add_node(g, "subtask A", child_run_id="sub_123")
check("C1 node carries child_run_id", n.get("child_run_id") == "sub_123", str(n.get("child_run_id")))

child = taskgraph.ensure("sub_123", session_id="sub_123", goal="child goal")
taskgraph.apply_write_todos(child, [{"label": "passo figlio 1"}, {"label": "passo figlio 2"}])
check("C2 child has its own list", len(taskgraph.load("sub_123")["nodes"]) == 2, "")
check("C3 parent list is separate", len(taskgraph.load("run_child1")["nodes"]) == 1, "")

from sparkforge import keepgoing  # noqa: E402
from sparkforge import subagent  # noqa: E402
check("C4 depth limit enforced", subagent.depth_allowed(2, 2) is False, "")
check("C5 depth allowed below cap", subagent.depth_allowed(1, 2) is True, "")

from sparkforge import server  # noqa: E402
from unittest import mock

with mock.patch.object(subagent, "spawn", return_value={
        "subagent_id": "sub_zzzz", "run_id": "run_child_x", "goal": "delegate"}) as _m:
    server.apply_agent_action(
        {"action": "subagent", "goal": "delegate", "max_steps": 2},
        run_id="run_parent_x", session="run_parent_x")
    _depth = _m.call_args.kwargs.get("depth")
taskgraph.ensure("run_child_x", session_id="run_child_x", goal="delegate")
pnode = taskgraph.load("run_parent_x")["nodes"][0]
check("C6 child_run_id links to child run_id (not subagent_id)",
      pnode["child_run_id"] == "run_child_x", str(pnode["child_run_id"]))
check("C7 link resolves to the child graph",
      taskgraph.load(pnode["child_run_id"]) is not None, str(pnode["child_run_id"]))
check("C8 spawn depth propagates from parent (1)", _depth == 1, str(_depth))
nested = subagent.depth_of("run_L1") + 1
check("C9 second nested spawn refused at cap=1",
      subagent.depth_allowed(0, 1) is True and subagent.depth_allowed(nested, 1) is False,
      "nested_depth=%d" % nested)

total = len(results)
print("\n==== %d/%d checks passed ====" % (sum(results), total))
sys.exit(0 if all(results) else 1)