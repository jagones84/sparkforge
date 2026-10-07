#!/usr/bin/env python3
"""v206 — step auditor read-only + evidence gating (RDD P1 / JAG-205+).

Deterministic, no model. Proves a "risky" task node (requires_proof) may only be
marked `done` when it carries an OBSERVED evidence entry (environment proof), not
merely a claim. A read-only `audit_node()` reports the verdict.

  A) baseline: a normal node still closes with a plain claim;
  B) a requires_proof node is REFUSED when marked done with a claim only;
  C) it closes once an observed evidence entry is attached; audit flips to ok;
  D) complete_node(observed=True) closes; without proof it is refused;
  E) audit_node on an unknown id fails safe (ok False, no raise).

Run:  python3 tests/v206_task_auditor.py
"""
import atexit
import os
import shutil
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_tmp = tempfile.mkdtemp(prefix="sf-206-")
atexit.register(lambda: shutil.rmtree(_tmp, ignore_errors=True))
os.environ["SPARKFORGE_GRAPH_DIR"] = _tmp
sys.path.insert(0, os.path.join(REPO, "src"))

from sparkforge import taskgraph  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


g = taskgraph.ensure("run_aud", session_id="run_aud", goal="audit")


def status(nid):
    n = taskgraph.find(g, nid)
    return n["status"] if n else None


# ---- A: baseline (a normal node closes with a claim) ----
n0 = taskgraph.add_node(g, "normal step")
try:
    taskgraph.update_node(g, n0["id"], status="done", evidence="plain claim")
    ok0 = status(n0["id"]) == "done"
except Exception as e:  # noqa: BLE001
    ok0 = False
check("A1 non-proof node closes with a claim", ok0)

# ---- B: requires_proof node refuses a claim-only done ----
try:
    n1 = taskgraph.add_node(g, "risky deploy", requires_proof=True)
    rp = n1.get("requires_proof") is True
except TypeError:
    n1, rp = None, False
check("B1 add_node stores requires_proof", rp)

refused = False
if n1:
    try:
        taskgraph.update_node(g, n1["id"], status="done", evidence="trust me, it works")
    except ValueError:
        refused = True
    except Exception:  # noqa: BLE001
        refused = False
check("B2 done WITHOUT environment proof is REFUSED", refused)
check("B3 node did NOT close (still not done)",
      n1 is not None and status(n1["id"]) != "done", str(status(n1["id"]) if n1 else None))

# ---- C: audit read-only, then close with observed proof ----
a = None
try:
    a = taskgraph.audit_node(g, n1["id"])
except Exception:  # noqa: BLE001
    a = None
check("C1 audit_node reports no proof (ok False)",
      bool(a) and a.get("has_proof") is False and a.get("ok") is False,
      str(a)[:80])

closed = False
if n1:
    try:
        taskgraph.update_node(g, n1["id"], status="done",
                              evidence=[{"text": "pytest: 42 passed", "observed": True}])
        closed = status(n1["id"]) == "done"
    except Exception:  # noqa: BLE001
        closed = False
check("C2 done WITH observed proof closes", closed)

a2 = taskgraph.audit_node(g, n1["id"]) if n1 else {}
check("C3 audit flips to ok/has_proof", a2.get("ok") is True and a2.get("has_proof") is True,
      str(a2)[:80])

# ---- D: complete_node observed flag ----
n2 = None
cc = False
try:
    n2 = taskgraph.add_node(g, "risky migrate", requires_proof=True)
    taskgraph.complete_node(g, node_id=n2["id"], evidence="ran migration", observed=True)
    cc = status(n2["id"]) == "done"
except Exception:  # noqa: BLE001
    cc = False
check("D1 complete_node(observed=True) closes", cc)

refused2 = False
try:
    n3 = taskgraph.add_node(g, "risky x", requires_proof=True)
    taskgraph.complete_node(g, node_id=n3["id"], evidence="claim only")
except ValueError:
    refused2 = True
except Exception:  # noqa: BLE001
    refused2 = False
check("D2 complete_node without proof refused", refused2)

# ---- E: unknown id fails safe ----
try:
    a3 = taskgraph.audit_node(g, "does_not_exist")
    safe = (a3.get("ok") is False)
except Exception:  # noqa: BLE001
    safe = False
check("E1 audit_node on unknown id fails safe", safe)

ok = sum(results)
print("\nv206: %d/%d PASS" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)
