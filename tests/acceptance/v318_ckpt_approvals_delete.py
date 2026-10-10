#!/usr/bin/env python3
"""v318 — checkpoints and approvals can be truly DELETED (JAG-318).

Neither module had any delete: snapshots and the approval queue only ever grew.
JAG-318 adds real deletion
  * checkpoints.delete(id)  → drop the manifest AND unlink the payload file;
  * checkpoints.prune(keep) → drop the oldest overflow (index + payloads);
  * approvals.delete(id)    → remove one record and its threading.Event;
  * approvals.clear(status) → drop decided records (pending kept by default);
plus HTTP DELETE routes and CLI (`checkpoints rm|prune`, `approvals rm|clear`).

Deterministic, no model. Run:  python3 tests/acceptance/v318_ckpt_approvals_delete.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.memory import checkpoints as cp  # noqa: E402
from longrun.tools import approvals as ap  # noqa: E402

TMP = tempfile.mkdtemp(prefix="sf-318-")
cp.CKPT_DIR = os.path.join(TMP, "ckpt")
ap.PATH = os.path.join(TMP, "approvals.json")
ap.DATA_DIR = TMP
ap._store = None
ap._events = {}

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


class FakeSrv:
    def load_plan(self):
        return {"steps": []}

    def load_tasks(self):
        return {"tasks": []}

    def load_session(self, sid):
        return None

    def save_plan(self, p):
        pass

    def save_tasks(self, t):
        pass

    def save_session(self, s):
        pass


cp._srv = lambda: FakeSrv()

# ---- A: checkpoint delete is a TRUE delete ---------------------------------
a = cp.create(label="a")
b = cp.create(label="b")
check("A1 two checkpoints exist", len(cp.list_checkpoints()) == 2, str(len(cp.list_checkpoints())))
check("A2 the payload file exists", os.path.isfile(cp._snapshot_path(a["id"])))
res = cp.delete(a["id"])
check("A3 delete reports ok", res.get("ok") and res.get("deleted") == a["id"], str(res))
check("A4 the manifest is gone", cp.get(a["id"]) is None)
check("A5 the payload file is unlinked", not os.path.isfile(cp._snapshot_path(a["id"])))
check("A6 the other checkpoint survives", cp.get(b["id"]) is not None)
check("A7 deleting an unknown id is refused", cp.delete("cp_nope").get("ok") is False)

# ---- B: prune drops the oldest beyond `keep` -------------------------------
for i in range(4):
    cp.create(label="extra-%d" % i)
check("B1 five checkpoints exist (b + 4)", len(cp.list_checkpoints()) == 5,
      str(len(cp.list_checkpoints())))
oldest = cp.list_checkpoints()[-1]["id"]
res2 = cp.prune(keep=2)
check("B2 prune removed the overflow", res2.get("ok") and res2.get("removed") == 3, str(res2))
check("B3 exactly two remain", len(cp.list_checkpoints()) == 2)
check("B4 the oldest payload is unlinked", not os.path.isfile(cp._snapshot_path(oldest)))
check("B5 prune is idempotent", cp.prune(keep=2).get("removed") == 0)

# ---- C: approval delete + clear --------------------------------------------
p1 = ap.create("shell", {"command": "ls"}, run_id="r1", decision="pending")
p2 = ap.create("fs.write", {"path": "/x"}, run_id="r1", decision="auto_approved")
p3 = ap.create("git", {"args": "push"}, run_id="r1")
ap.decide(p3["id"], "deny", by="tester")
check("C1 three approvals stored", ap.stats()["total"] == 3, str(ap.stats()))
check("C2 an event exists for the pending one", p1["id"] in ap._events)

# delete a DECIDED record so the pending one stays and keep_pending is exercised
res3 = ap.delete(p2["id"])
check("C3 delete removes the record", res3.get("ok") and res3.get("removed") == 1, str(res3))
check("C4 no event leaks (deleted id absent)", p2["id"] not in ap._events)
check("C5 total dropped to two, pending kept", ap.stats()["total"] == 2
      and ap.stats()["pending"] == 1, str(ap.stats()))

res4 = ap.clear()
check("C6 clear removes decided but KEEPS pending", res4.get("removed") == 1, str(res4))
check("C7 the pending approval survives, decided are gone",
      ap.stats()["pending"] == 1 and ap.stats()["approved"] == 0
      and ap.stats()["denied"] == 0, str(ap.stats()))
_before = ap.stats()["total"]
check("C8 clear(all) empties the queue",
      ap.clear(keep_pending=False).get("removed") == _before and ap.stats()["total"] == 0,
      str(ap.stats()))

# ---- D: source wiring ------------------------------------------------------
cpsrc = open(os.path.join(REPO, "src", "longrun", "memory/checkpoints.py"), encoding="utf-8").read()
apsrc = open(os.path.join(REPO, "src", "longrun", "tools/approvals.py"), encoding="utf-8").read()
apisrc = open(os.path.join(REPO, "src", "longrun", "core/api_v02.py"), encoding="utf-8").read()
check("D1 checkpoints.delete + prune exist", "def delete(" in cpsrc and "def prune(" in cpsrc)
check("D2 approvals.delete + clear exist", "def delete(" in apsrc and "def clear(" in apsrc)
check("D3 DELETE /api/checkpoints is wired", 'path == "/api/checkpoints":' in apisrc)
check("D4 DELETE /api/approvals is wired", 'path == "/api/approvals":' in apisrc)

print("---")
ok = sum(1 for r in results if r)
print("%d/%d PASS" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)

