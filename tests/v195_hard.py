#!/usr/bin/env python3
"""v195 — HARD / adversarial suite (JAG-191/192/194).

Deterministic, no model, no network, isolated temp data dirs. It tries to break
the parts that the earlier reload bugs touched, plus concurrency:

  A) fs.edit resolves RELATIVE paths inside the session workspace (JAG-191).
  B) two workspaces writing the SAME relative name concurrently stay isolated.
  C) a file op OUTSIDE the session workspace escalates to `required`, inside not.
  D) malformed / failing tool inputs degrade gracefully (never raise).
  E) a new plan numbers nodes monotonically and NEVER reuses ids (JAG-194).
  F) 20 concurrent add_node on one graph lose nothing (GRAPH_LOCK).

Run:  python3 tests/v195_hard.py
"""
import atexit
import json
import os
import shutil
import sys
import tempfile
import threading

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
tmp = tempfile.mkdtemp(prefix="sf-195-")
atexit.register(lambda: shutil.rmtree(tmp, ignore_errors=True))
os.environ["SPARKFORGE_CONFIG_DIR"] = os.path.join(tmp, "cfg")
os.environ["SPARKFORGE_SESSIONS_DIR"] = os.path.join(tmp, "sessions")
os.environ["SPARKFORGE_DB"] = os.path.join(tmp, "events.db")
os.environ["SPARKFORGE_GRAPH_DIR"] = os.path.join(tmp, "graphs")
os.environ["SPARKFORGE_EDITS_DIR"] = os.path.join(tmp, "edits")
os.environ["SPARKFORGE_RUNS_DIR"] = os.path.join(tmp, "runs")
for d in ("cfg", "sessions", "graphs", "edits", "runs"):
    os.makedirs(os.path.join(tmp, d), exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from sparkforge import registry, taskgraph, tools  # noqa: E402
from sparkforge import server as _srv  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


def wsdir(name):
    """A workspace under an allowed root (REPO) so resolve_path accepts it."""
    p = os.path.join(REPO, "data", "v195-%s-%d" % (name, os.getpid()))
    os.makedirs(p, exist_ok=True)
    atexit.register(lambda: shutil.rmtree(p, ignore_errors=True))
    return p


# ---- A: fs.edit resolves relative to the workspace (JAG-191) ----------------
wa = wsdir("A")
tools.execute("fs.write", {"path": "e.txt", "content": "alpha beta", "workspace": wa})
ra = tools.execute("fs.edit", {"path": "e.txt", "search": "beta", "replace": "BETA",
                               "workspace": wa})
check("A1 fs.edit relative lands in the workspace",
      ra.get("ok") and ra.get("path") == os.path.join(wa, "e.txt"), "%s" % ra.get("path"))
check("A2 fs.edit really applied",
      open(os.path.join(wa, "e.txt"), encoding="utf-8").read() == "alpha BETA", "")


# ---- B: concurrent writes to 2 workspaces, same name, isolated -------------
wA, wB = wsdir("BA"), wsdir("BB")
res = {}


def _write(tag, ws, txt):
    rr = tools.execute("fs.write", {"path": "same.txt", "content": txt, "workspace": ws})
    res[tag] = rr.get("path")


ths = [threading.Thread(target=_write, args=("A", wA, "AAA")),
       threading.Thread(target=_write, args=("B", wB, "BBB"))]
[t.start() for t in ths]
[t.join() for t in ths]
ok_b = (res.get("A") == os.path.join(wA, "same.txt")
        and res.get("B") == os.path.join(wB, "same.txt")
        and open(os.path.join(wA, "same.txt"), encoding="utf-8").read() == "AAA"
        and open(os.path.join(wB, "same.txt"), encoding="utf-8").read() == "BBB")
check("B1 concurrent fs.write isolated per workspace", ok_b, str(res))


# ---- C: outside-workspace gating under the DEFAULT policy ------------------
_cfg = json.loads(json.dumps(registry.load_config()))
_cfg.setdefault("approvals", {})
_cfg["approvals"]["mode"] = "normal"
_cfg["approvals"]["outside_workspace"] = "required"
_real_load = registry.load_config
registry.load_config = lambda reload=False: _cfg
try:
    wc = wsdir("C")
    outside = os.path.join(REPO, "data", "v195-outside.txt")
    check("C1 fs.read INSIDE the workspace stays auto",
          registry.classify("fs.read", {"path": "in.txt"}, workspace=wc)[0] == "auto",
          str(registry.classify("fs.read", {"path": "in.txt"}, workspace=wc)))
    check("C2 fs.write OUTSIDE the workspace is required",
          registry.classify("fs.write", {"path": outside}, workspace=wc)[0] == "required",
          str(registry.classify("fs.write", {"path": outside}, workspace=wc)))
finally:
    registry.load_config = _real_load


# ---- D: malformed / failing inputs degrade gracefully ----------------------
d_ok = True
d_detail = []
_cases = [
    ("shell", {"command": ""}),                                            # empty
    ("fs.read", {"path": os.path.join(wa, "nope.txt"), "workspace": wa}),  # missing
    ("fs.edit", {"path": os.path.join(wa, "e.txt"), "search": "zzz",
                 "replace": "y", "workspace": wa}),                        # no match
    ("fs.read", {"path": "/etc/hostname"}),                                # outside roots
]
for tool, args in _cases:
    try:
        rr = tools.execute(tool, args)
        if not isinstance(rr, dict) or rr.get("ok") is not False:
            d_ok = False
            d_detail.append("%s -> ok=%s" % (tool, rr.get("ok") if isinstance(rr, dict) else rr))
    except Exception as e:  # noqa: BLE001
        d_ok = False
        d_detail.append("%s raised %r" % (tool, e))
check("D1 malformed inputs fail gracefully (no raise, ok=False)", d_ok, "; ".join(d_detail))


# ---- E: new plans number nodes monotonically, never reuse ids --------------
g = taskgraph.ensure("v195-plan")
ids = [taskgraph.add_node(g, "p0 step", status="todo")["id"]]
plans = [0]
for r in range(1, 4):
    taskgraph.begin_plan(g)
    g = taskgraph.load("v195-plan")
    node = taskgraph.add_node(g, "p%d step" % r, status="todo")
    ids.append(node["id"])
    plans.append(node.get("plan"))
check("E1 node ids never reused across plans", len(set(ids)) == 4, "ids=%s" % ids)
check("E2 ids are strictly increasing",
      [int(x[1:]) for x in ids] == sorted(int(x[1:]) for x in ids), "ids=%s" % ids)
check("E3 every plan keeps its own nodes tagged",
      plans == [0, 1, 2, 3], "plans=%s" % plans)


# ---- F: 20 concurrent add_node on one graph lose nothing -------------------
gc = taskgraph.ensure("v195-conc")


def _add(i):
    taskgraph.add_node(gc, "c%d" % i, status="todo")


fths = [threading.Thread(target=_add, args=(i,)) for i in range(20)]
[t.start() for t in fths]
[t.join() for t in fths]
saved = taskgraph.load("v195-conc") or {}
check("F1 concurrent add_node keeps all 20 nodes",
      len(saved.get("nodes", [])) == 20, "nodes=%d" % len(saved.get("nodes", [])))
check("F2 concurrent add_node kept unique ids",
      len({n["id"] for n in saved.get("nodes", [])}) == 20,
      "ids=%d" % len({n["id"] for n in saved.get("nodes", [])}))


# ---- G: update_todos indices resolve inside the CURRENT plan (JAG-196) ------
# Keeping old plans (JAG-194) must NOT let an old node shadow the current plan:
# `index: 0` has to hit the current plan's first node, not the graph's first node.
gg = taskgraph.ensure("v195-resolve")
taskgraph.add_node(gg, "old A", status="done", evidence="x")
taskgraph.begin_plan(gg)
gg = taskgraph.load("v195-resolve")
n1 = taskgraph.add_node(gg, "new A", status="todo")
n2 = taskgraph.add_node(gg, "new B", status="todo")
r0 = _srv._resolve_graph_node(gg, {"index": 0})
r1 = _srv._resolve_graph_node(gg, {"index": 1})
check("G1 index 0 -> current plan's FIRST node",
      r0 and r0["id"] == n1["id"], str(r0 and r0["id"]))
check("G2 index 1 -> current plan's node",
      r1 and r1["id"] == n2["id"], str(r1 and r1["id"]))
check("G3 label lookup stays inside the current plan",
      _srv._resolve_graph_node(gg, {"label": "old a"}) is None
      and (_srv._resolve_graph_node(gg, {"label": "new b"}) or {}).get("id") == n2["id"], "")
check("G4 _missing still dedupes within the current plan",
      len(taskgraph._missing(gg, [{"label": "new A"}])) == 0, "")
check("G5 _missing does NOT drop a re-used label from an old plan",
      len(taskgraph._missing(gg, [{"label": "old A"}])) == 1, "")


print("\n==== %d/%d checks passed ====" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
