#!/usr/bin/env python3
"""v215 — an operator "+ node" on a fresh session must CREATE the graph.

Regression for the bug found in the WebUI sweep (JAG-215): the Plan panel's "+"
on a session with no run graph yet wrote to the dead legacy /api/tasks board, so
the node vanished. `graph_post` now creates the graph on an "add". A non-add
action on a missing graph must still 404.

Deterministic, no model. Run:  python3 tests/v215_graph_ensure.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
tmp = tempfile.mkdtemp(prefix="sf-215-")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(tmp, "cfg")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(tmp, "sessions")
os.environ["LONGRUN_DB"] = os.path.join(tmp, "events.db")
os.environ["LONGRUN_GRAPH_DIR"] = os.path.join(tmp, "graphs")
os.environ["LONGRUN_EDITS_DIR"] = os.path.join(tmp, "edits")
os.environ["LONGRUN_RUNS_DIR"] = os.path.join(tmp, "runs")
for d in ("cfg", "sessions", "graphs", "edits", "runs"):
    os.makedirs(os.path.join(tmp, d), exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun import server      # noqa: E402
from longrun import taskgraph   # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


RID = "fresh-" + os.urandom(4).hex()

# ---- A: "+" on a session with no graph creates the graph -------------------
node, err, code = server.graph_post(RID, {"action": "add", "label": "primo nodo"})
check("A1 add on fresh run returns 200", code == 200 and err is None,
      "code=%s err=%s" % (code, err))
check("A2 the node has an id + the label", bool(node) and node.get("id")
      and node.get("label") == "primo nodo", "node=%s" % (node,))
g = taskgraph.load(RID)
check("A3 the graph now exists with 1 node",
      bool(g) and len(g.get("nodes", [])) == 1,
      "nodes=%s" % (len((g or {}).get('nodes', []))))

# ---- B: a second "+" appends to the SAME graph -----------------------------
node2, err2, code2 = server.graph_post(RID, {"action": "add", "label": "secondo nodo"})
g2 = taskgraph.load(RID)
check("B1 second add returns 200", code2 == 200 and err2 is None, "code=%s" % code2)
check("B2 graph now has 2 nodes", bool(g2) and len(g2.get("nodes", [])) == 2,
      "nodes=%s" % (len((g2 or {}).get('nodes', []))))

# ---- C: the public payload reflects the nodes ------------------------------
pub = taskgraph.public(g2)
labels = [n.get("label") for n in pub.get("nodes", [])]
check("C1 public graph lists both labels",
      "primo nodo" in labels and "secondo nodo" in labels, "labels=%s" % labels)

# ---- D: a non-add action on a MISSING graph still 404 ----------------------
old, oerr, ocode = server.graph_post("missing-" + os.urandom(3).hex(),
                                     {"action": "complete", "id": "nope"})
check("D1 complete on missing graph -> 404 (unchanged)",
      ocode == 404 and oerr is not None, "code=%s err=%s" % (ocode, oerr))

# ---- E: the id/label are intact (no coercion surprises) --------------------
check("E1 node id is a non-empty string",
      isinstance(node.get("id"), str) and len(node["id"]) > 0, "id=%r" % node.get("id"))

print("---")
ok = sum(1 for r in results if r)
print("%d/%d PASS" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)
