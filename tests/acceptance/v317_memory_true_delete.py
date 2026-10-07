#!/usr/bin/env python3
"""v317 — memory: a TRUE delete, distinct from the soft tombstone (JAG-317).

`invalidate` (JAG-204) is append-only: the record STAYS on disk and is merely
hidden from recall. The agent's `forget` action was an alias of it — misleading,
because nothing was ever removed. JAG-317 adds real physical deletion:

  * memory.forget(mid)      → rewrites the owning file without the record and
                              drops the tombstone that targeted it;
  * memory.purge_invalidated() → bulk-compacts every invalidated/expired record;
  * tool action=forget/-purge, DELETE /api/memory?target=, CLI `memory forget`.

Deterministic, no model. Run:  python3 tests/acceptance/v317_memory_true_delete.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "src"))

from sparkforge import memory as mem  # noqa: E402
from sparkforge import tools  # noqa: E402

TMP = tempfile.mkdtemp(prefix="sf-317-")
mem.DATA_DIR = TMP                 # isolate from the live data/memory
mem.CORE_PATH = os.path.join(TMP, "core.md")
mem._vector_db = None

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


def mids():
    return {r.get("mid") for r in mem.query(None, "memory.store", 1000)}


def on_disk(mid):
    p = mem._path("memory.store")
    if not os.path.isfile(p):
        return False
    with open(p, encoding="utf-8") as f:
        return mid in f.read()


# ---- A: forget is a TRUE delete --------------------------------------------
r1 = mem.store("memory.store", "the capital of France is Paris")
r2 = mem.store("memory.store", "the capital of Italy is Rome")
mid1, mid2 = r1["mid"], r2["mid"]
check("A1 both records are readable", {mid1, mid2} <= mids())
check("A2 the record is physically on disk", on_disk(mid1))

# a soft invalidate keeps the bytes on disk (this is the JAG-204 contract)
mem.invalidate(mid1, reason="wrong")
check("A3 invalidate is soft: bytes still on disk", on_disk(mid1))
check("A4 invalidate hides it from governed recall",
      all(r.get("mid") != mid1 for r in mem.governed_query(kind="memory.store", limit=50)))

res = mem.forget(mid1)
check("A5 forget reports a removal", res.get("ok") and res.get("removed", 0) >= 1,
      str(res))
check("A6 the record is GONE from disk", not on_disk(mid1))
check("A7 the record is gone from query", mid1 not in mids())
check("A8 the tombstone that targeted it was dropped", mid1 not in mem.invalid_targets())
check("A9 the OTHER record is untouched", mid2 in mids() and on_disk(mid2))

# ---- B: purge_invalidated compacts the store -------------------------------
mem.invalidate(mid2, reason="stale")
check("B1 the record is still on disk after invalidate", on_disk(mid2))
res2 = mem.purge_invalidated()
check("B2 purge reports the removal", res2.get("ok") and res2.get("removed", 0) >= 1,
      str(res2))
check("B3 the invalidated record is physically gone", not on_disk(mid2))
check("B4 no tombstones remain", mem.invalid_targets() == set())

# ---- C: tool wiring: forget is not an alias of invalidate ------------------
r3 = mem.store("memory.store", "gadgets are obsolete")
out = tools._memory({"action": "forget", "target": r3["mid"]}, "run-317")
check("C1 tool action=forget removes the record", not on_disk(r3["mid"]), str(out))
r4 = mem.store("memory.store", "widgets are deprecated")
mem.invalidate(r4["mid"], reason="x")
out2 = tools._memory({"action": "purge"}, "run-317")
check("C2 tool action=purge removes invalidated records", not on_disk(r4["mid"]), str(out2))

# ---- D: source wiring ------------------------------------------------------
msrc = open(os.path.join(REPO, "src", "sparkforge", "memory.py"), encoding="utf-8").read()
check("D1 memory.forget exists", "def forget(" in msrc)
check("D2 memory.purge_invalidated exists", "def purge_invalidated(" in msrc)
asrc = open(os.path.join(REPO, "src", "sparkforge", "api_v02.py"), encoding="utf-8").read()
check("D3 DELETE /api/memory is wired", 'if path == "/api/memory":' in asrc)

print("---")
ok = sum(1 for r in results if r)
print("%d/%d PASS" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)
