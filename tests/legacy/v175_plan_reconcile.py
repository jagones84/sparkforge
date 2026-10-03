"""v175 — autonomous PLAN RECONCILIATION (JAG-177).

The system must clean its own plan: a re-plan REPLACES the previous open plan
(stale/obsolete open steps are cancelled, done history preserved), and at most ONE
step is 'doing' at a time. This is what stops re-planning from accumulating a wall
of overlapping nodes (session `test`: 27 nodes from 3 re-plans).

Run:  python3 tests/v175_plan_reconcile.py
"""
import os
import sys

REPO = "/home/jagones/Repositories/sparkforge"
os.chdir(REPO)
sys.path.insert(0, os.path.join(REPO, "src"))

import py_compile
py_compile.compile(os.path.join(REPO, "src", "sparkforge", "taskgraph.py"), doraise=True)
py_compile.compile(os.path.join(REPO, "src", "sparkforge", "server.py"), doraise=True)
print("[compile] taskgraph.py + server.py OK")

from sparkforge import taskgraph as tg
import time

_K = "v175-%d" % int(time.time() * 1000)

# A) a re-plan supersedes the open plan but never touches DONE history
g = tg.ensure(_K + "a", session_id=_K + "a")
tg.apply_write_todos(g, [{"label": "Step A"}, {"label": "Step B"}])
done_id = g["nodes"][0]["id"]
tg.update_node(g, done_id, status="done", evidence="ran, exit 0",
               source="model:update_todos")
sup = tg.supersede_open(g, ["Step C"])
by_id = {n["id"]: n for n in g["nodes"]}
print("A statuses:", {n["label"]: n["status"] for n in g["nodes"]}, "superseded:", sup)
assert by_id[done_id]["status"] == "done", "supersede destroyed a DONE node"
assert done_id not in sup, "the DONE node was superseded"
assert sup and all(by_id[i]["status"] == "cancelled" for i in sup), \
    "stale OPEN steps were not superseded"
print("A: re-plan replaces the open plan, keeps done history OK")

# B) at most one 'doing'
g2 = tg.ensure(_K + "b", session_id=_K + "b")
tg.apply_write_todos(g2, [{"label": "X"}, {"label": "Y"}, {"label": "Z"}])
ids = [n["id"] for n in g2["nodes"]]
for i in ids:
    tg.update_node(g2, i, status="doing")
dem = tg.enforce_single_doing(g2)
doing = [n["id"] for n in g2["nodes"] if n["status"] == "doing"]
print("B doing:", doing, "demoted:", dem)
assert len(doing) == 1, "more than one 'doing' left: %s" % doing
assert len(dem) == 2, "expected 2 demoted, got %d" % len(dem)
print("B: single 'doing' enforced OK")

# C) the server wires both into the model's plan actions
srv = open(os.path.join(REPO, "src", "sparkforge", "server.py"), encoding="utf-8").read()
assert "taskgraph.supersede_open(graph, _labels)" in srv, \
    "write_todos does not supersede the previous plan"
assert "taskgraph.enforce_single_doing(graph)" in srv, \
    "update_todos does not enforce a single 'doing'"
print("C: server wiring OK")

print("RESULT: ALL OK")
