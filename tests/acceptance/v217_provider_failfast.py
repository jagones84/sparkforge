#!/usr/bin/env python3
"""v217 — a provider whose host is UNREACHABLE must fail fast, not hang.

Regression (JAG-217): a blackholed host (e.g. an offline Tailscale peer such as
the `win:` provider) made urlopen block for the whole OS connect timeout —
measured 140s for one chat turn — before the fallback chain moved on, so the turn
looked hung. Now `_router_stream` probes the endpoint with a short TCP connect and
raises immediately when it is unreachable, so failover is near-instant.

Deterministic, no real network (socket.create_connection is stubbed).
Run:  python3 tests/v217_provider_failfast.py
"""
import os
import socket
import sys
import tempfile
import time

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
tmp = tempfile.mkdtemp(prefix="sf-217-")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(tmp, "cfg")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(tmp, "sessions")
os.environ["LONGRUN_DB"] = os.path.join(tmp, "events.db")
os.environ["LONGRUN_GRAPH_DIR"] = os.path.join(tmp, "graphs")
os.environ["LONGRUN_EDITS_DIR"] = os.path.join(tmp, "edits")
os.environ["LONGRUN_RUNS_DIR"] = os.path.join(tmp, "runs")
for d in ("cfg", "sessions", "graphs", "edits", "runs"):
    os.makedirs(os.path.join(tmp, d), exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.core import server  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


_orig = socket.create_connection


class _FakeSock:
    def close(self):
        pass


def _unreachable(*a, **k):
    raise OSError(113, "No route to host")


# ---- A: _reachable is False on an unreachable host, and fast ----------------
socket.create_connection = _unreachable
try:
    t0 = time.time()
    r = server._reachable("http://192.0.2.1:9/v1/chat/completions")
    dt = time.time() - t0
    check("A1 _reachable(host offline) is False", r is False, "r=%s" % r)
    check("A2 the probe returns immediately (no OS connect wait)", dt < 1.0,
          "%.3fs" % dt)

    # ---- B: _router_stream raises FAST for an unreachable provider ----------
    t0 = time.time()
    raised = False
    try:
        server._router_stream([{"role": "user", "content": "hi"}], "win:x",
                              lambda ch, t: None)
    except Exception as e:  # noqa: BLE001
        raised = True
        err = str(e)
    dt = time.time() - t0
    check("B1 _router_stream raises for an unreachable provider", raised, "")
    check("B2 it fails FAST (<2s), never the ~140s OS timeout", dt < 2.0,
          "%.3fs" % dt)
finally:
    socket.create_connection = _orig

# ---- C: a reachable host passes the probe ----------------------------------
socket.create_connection = lambda *a, **k: _FakeSock()
try:
    check("C1 _reachable(host up) is True",
          server._reachable("http://127.0.0.1:9/x") is True, "")
finally:
    socket.create_connection = _orig

# ---- D: a URL with no host passes (never blocks) ---------------------------
check("D1 no-host URL is treated as reachable (no false block)",
      server._reachable("unix:///tmp/sock") is True, "")

# ---- E: CONNECT_TIMEOUT is bounded -----------------------------------------
check("E1 CONNECT_TIMEOUT is small and configurable",
      0 < server.CONNECT_TIMEOUT <= 10, "timeout=%s" % server.CONNECT_TIMEOUT)

print("---")
ok = sum(1 for r in results if r)
print("%d/%d PASS" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)

