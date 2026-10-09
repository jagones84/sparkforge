#!/usr/bin/env python3
"""v298 — events-log performance + bounded growth (JAG-300).

Locked here:
  * the events DB opens in WAL mode with synchronous=NORMAL (the log writes one row
    per streaming delta; the old rollback journal + FULL made every publish an
    fsync — measured 6.0 ms/call, now ~0.03 ms);
  * `prune_events` keeps the newest N rows and removes the rest in bounded batches;
  * a periodic pruner is wired into main().

Deterministic, no live model. Run: python3 tests/v298_perf.py
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "src"))
sys.path.insert(0, os.path.join(REPO, "src2"))

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


def read(*parts):
    with open(os.path.join(REPO, *parts), encoding="utf-8") as f:
        return f.read()


from sparkforge import server as srv  # noqa: E402

jm = srv.db().execute("PRAGMA journal_mode").fetchone()[0]
sy = srv.db().execute("PRAGMA synchronous").fetchone()[0]
check("events DB is in WAL mode", str(jm).lower() == "wal", "got %r" % jm)
check("events DB uses synchronous=NORMAL", int(sy) == 1, "got %r" % sy)

check("EVENTS_KEEP is a positive int", isinstance(srv.EVENTS_KEEP, int) and srv.EVENTS_KEEP > 0)
check("prune_events exists", callable(getattr(srv, "prune_events", None)))
check("periodic pruner exists", callable(getattr(srv, "_start_event_pruning", None)))

# fill then prune
for i in range(300):
    srv.publish("perf.regress", n=i)
mx_before = srv.db().execute("SELECT MAX(id) FROM events").fetchone()[0]
n_before = srv.db().execute("SELECT COUNT(*) FROM events").fetchone()[0]
check("events were written", n_before >= 300)

removed = srv.prune_events(keep=100)
n_after = srv.db().execute("SELECT COUNT(*) FROM events").fetchone()[0]
mx_after = srv.db().execute("SELECT MAX(id) FROM events").fetchone()[0]
mn_after = srv.db().execute("SELECT MIN(id) FROM events").fetchone()[0]
check("prune removed the excess", removed >= n_before - 100, "removed=%d before=%d" % (removed, n_before))
check("prune keeps at most `keep` rows", n_after <= 100, "after=%d" % n_after)
check("prune keeps the NEWEST row", mx_after == mx_before)
check("prune dropped the OLDEST rows", mn_after > 0 and (mx_after - mn_after) < 100)

# idempotent when already under the cap
check("prune is a no-op under the cap", srv.prune_events(keep=100) == 0)

src = read("src", "sparkforge", "server.py") + read("src", "sparkforge", "httpapi.py")
ev = read("src", "sparkforge", "events.py")
check("WAL pragma is set", "PRAGMA journal_mode=WAL" in ev)
check("NORMAL pragma is set", "PRAGMA synchronous=NORMAL" in ev)
check("pruner is started in main()", "_start_event_pruning()" in src)

# JAG-300: the attention route must not read the roster twice per poll.
from orbit_beta.attention import AttentionFeed  # noqa: E402
import inspect  # noqa: E402

sig = inspect.signature(AttentionFeed.snapshot)
check("snapshot() accepts an optional session roster", "sessions" in sig.parameters,
      "params=%s" % list(sig.parameters))
orbit_api = read("src2", "orbit_beta", "api.py")
check("attention route passes the roster to snapshot()",
      "snap = _ATTN.snapshot(sessions)" in orbit_api)
check("decision queue reuses one roster read",
      "self.feed.snapshot(sessions)" in read("src2", "orbit_beta", "decisions.py"))

# JAG-300: the budget alert must be measured against the SESSION's own model.
_saved_ctx = srv.context_usage
_saved_resolve = srv.resolve_ctx_model
_seen = {}


def _fake_ctx(session_id, message=None, model=None):
    _seen["model"] = model
    _seen["sid"] = session_id
    return {"pct": 0.0}


srv.context_usage = _fake_ctx
srv.resolve_ctx_model = lambda sess, model=None: "sentinel-model"
try:
    AttentionFeed(registry=None)._budget(srv, {"id": "S1", "model": "small-window"})
finally:
    srv.context_usage = _saved_ctx
    srv.resolve_ctx_model = _saved_resolve
check("budget alert measures against the session's own model",
      _seen.get("model") == "sentinel-model", "got %r" % _seen.get("model"))
check("budget alert is checked for the given session id", _seen.get("sid") == "S1")

print("---")
passed = sum(results)
print("%d/%d PASS" % (passed, len(results)))
sys.exit(0 if passed == len(results) else 1)
