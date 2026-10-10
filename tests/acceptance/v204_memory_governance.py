#!/usr/bin/env python3
"""v204 — memory GOVERNANCE (JAG-204, RDD P2: BAVAR-lite).

Deterministic, no model. Proves persistent memory is verifiable/reusable:
  A) every store carries provenance (source) + a stable id (mid);
  B) a time-bounded memory (ttl_secs) expires and stops being recalled;
  C) a contradicted memory can be invalidated (append-only tombstone) and then
     disappears from governed recall + tool recall, while the raw record stays;
  D) health() reports expired / invalidated / no-source counts.

Run:  python3 tests/v204_memory_governance.py
"""
import atexit
import os
import shutil
import sys
import tempfile
import time

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
tmp = tempfile.mkdtemp(prefix="sf-204-")
atexit.register(lambda: shutil.rmtree(tmp, ignore_errors=True))
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(tmp, "cfg")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(tmp, "sessions")
os.environ["LONGRUN_DB"] = os.path.join(tmp, "events.db")
os.environ["LONGRUN_GRAPH_DIR"] = os.path.join(tmp, "graphs")
os.environ["LONGRUN_EDITS_DIR"] = os.path.join(tmp, "edits")
os.environ["LONGRUN_RUNS_DIR"] = os.path.join(tmp, "runs")
for d in ("cfg", "sessions", "graphs", "edits", "runs"):
    os.makedirs(os.path.join(tmp, d), exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun import memory as mem  # noqa: E402
from longrun import tools  # noqa: E402

# isolate the store: redirect DATA_DIR/CORE to the temp dir, force keyword path
mem.DATA_DIR = os.path.join(tmp, "memory")
mem.CORE_PATH = os.path.join(mem.DATA_DIR, "core.md")
os.makedirs(mem.DATA_DIR, exist_ok=True)
mem._vector_db = {}          # falsy → semantic_query falls back to keyword
mem._writes_since_index = 0  # avoid a rebuild over the empty dir mid-test

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


# ---- A: provenance + id on store (via the tool the agent actually calls) ----
r = tools._memory({"action": "store", "content": "alpha lesson about widgets",
                   "source": "unit-test"}, "run-a")
check("A1 store ok + returns mid", r.get("ok") and r.get("mid"), str(r.get("mid")))
mid_a = r.get("mid")
recs = mem.query(None, "memory.store", 1000)
rec_a = [x for x in recs if x.get("mid") == mid_a]
check("A2 stored record found by mid", len(rec_a) == 1, "n=%d" % len(rec_a))
check("A3 provenance recorded (source)", rec_a and rec_a[0].get("source") == "unit-test",
      rec_a[0].get("source") if rec_a else "none")
check("A4 mid is stable/typed", isinstance(mid_a, str) and len(mid_a) == 8, str(mid_a))

# default provenance when the caller omits source
r2 = tools._memory({"action": "store", "content": "beta lesson about gadgets"}, "run-a")
rec_b = [x for x in mem.query(None, "memory.store", 1000) if x.get("mid") == r2.get("mid")]
check("A5 default source=agent", rec_b and rec_b[0].get("source") == "agent",
      rec_b[0].get("source") if rec_b else "none")

# ---- B: expiry (ttl_secs) ----
rt = tools._memory({"action": "store", "content": "gamma ephemeral lesson",
                    "ttl_secs": 0.5}, "run-a")
mid_t = rt.get("mid")
rec_t = [x for x in mem.query(None, "memory.store", 1000) if x.get("mid") == mid_t]
check("B1 ttl recorded as expires_ts", rec_t and rec_t[0].get("expires_ts"),
      str(rec_t[0].get("expires_ts")) if rec_t else "none")
check("B2 not expired before deadline", rec_t and not mem.is_expired(rec_t[0]), "")
_deadline = time.time() + 3.0
while time.time() < _deadline and not (rec_t and mem.is_expired(rec_t[0])):
    time.sleep(0.02)
check("B3 expired after deadline", rec_t and mem.is_expired(rec_t[0]), "")
gq = mem.governed_query(kind="memory.store", limit=50)
check("B4 expired dropped from governed_query",
      all(x.get("mid") != mid_t for x in gq), "n=%d" % len(gq))

# ---- C: invalidation (append-only tombstone) ----
mem.invalidate(mid_a, reason="contradicted by newer evidence")
bad = mem.invalid_targets()
check("C1 tombstone recorded", mid_a in bad, str(sorted(bad))[:80])
check("C2 is_valid() flips to False", not mem.is_valid(rec_a[0]), "")
gq = mem.governed_query(kind="memory.store", limit=50)
check("C3 invalidated dropped from governed_query",
      all(x.get("mid") != mid_a for x in gq), "n=%d" % len(gq))
rrec = tools._memory({"action": "recall", "query": "alpha widgets", "limit": 20}, "run-a")
check("C4 invalidated dropped from tool recall",
      "alpha lesson" not in (rrec.get("stdout") or ""), (rrec.get("stdout") or "")[:80])
check("C5 raw record still on disk (append-only)",
      any(x.get("mid") == mid_a for x in mem.query(None, "memory.store", 1000)), "")
rrec2 = tools._memory({"action": "recall", "query": "alpha widgets", "limit": 20,
                       "include_invalid": True}, "run-a")
check("C6 include_invalid surfaces the tombstoned record",
      "alpha lesson" in (rrec2.get("stdout") or ""), (rrec2.get("stdout") or "")[:80])

# ---- C-bis: invalidate-by-query ----
rq = tools._memory({"action": "invalidate", "query": "gadgets"}, "run-a")
check("C7 invalidate-by-query ok", rq.get("ok") and rq.get("count", 0) >= 1,
      "count=%s" % rq.get("count"))

# ---- D: health report ----
h = mem.health()
check("D1 health counts stores", h.get("stores", 0) >= 3, str(h.get("stores")))
check("D2 health sees >=1 expired", h.get("expired", 0) >= 1, str(h.get("expired")))
check("D3 health sees >=1 invalidated", h.get("invalidated", 0) >= 1,
      str(h.get("invalidated")))
hh = tools._memory({"action": "health"}, "run-a")
check("D4 memory{health} tool returns a report", hh.get("ok") and "report" in hh, "")

# ---- E: front-matter TYPE fidelity (JAG-210 regression) ----
# A hex `mid` can be all digits; the parser used to coerce it to int, so a lookup
# by string id silently missed the record (~16% flake). Only numeric fields cast.
with open(mem._path("memory.store"), "a", encoding="utf-8") as _f:
    _f.write(mem._render_md({"mid": "33263015", "ts": 1.5, "kind": "memory.store",
                             "session": "12345", "source": "agent",
                             "content": "numeric-looking identity"}) + "\n")
_e = [x for x in mem.query(None, "memory.store", 1000)
      if x.get("content") == "numeric-looking identity"]
check("E1 all-digit mid stays a STRING", bool(_e) and _e[0].get("mid") == "33263015",
      repr(_e[0].get("mid")) if _e else "none")
check("E2 numeric-looking session stays a STRING",
      bool(_e) and _e[0].get("session") == "12345",
      repr(_e[0].get("session")) if _e else "none")
check("E3 numeric ts is still a float", bool(_e) and isinstance(_e[0].get("ts"), float),
      repr(_e[0].get("ts")) if _e else "none")

ok = sum(results)
print("\nv204: %d/%d PASS" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)
