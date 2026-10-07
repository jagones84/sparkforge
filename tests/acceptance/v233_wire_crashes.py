#!/usr/bin/env python3
"""v233 — wire-input crashes that DROPPED the HTTP connection (JAG-233..237).

A live surface fuzz (tests/live surface scan) sent malformed queries and
type-confused JSON bodies to every route. Each bug below closed the socket with
NO response (an unhandled exception surfaced as `socketserver` "Exception
occurred during processing of request" in the journal) — a trivially reachable
denial-of-availability:

  JAG-233  _send(code, None)      -> None.encode() AttributeError
                                     (GET /api/subagent?id=<unknown>)
  JAG-234  meta.candidate_label   -> None[:20] / %d on a str
                                     (POST /api/meta, even with an empty body)
  JAG-235  run_get(list)          -> unhashable dict key
                                     (POST /api/agent/control {"run_id":[1]})
  JAG-236  acp connect(int url)   -> int.rstrip AttributeError
                                     (POST /api/acp/connect {"url":999})
  JAG-237  mcp disconnect_all     -> "dictionary changed size during iteration"
                                     (POST /api/mcp/reload racing a start)

Deterministic, no live server, no network. Run:  python3 tests/v233_wire_crashes.py
"""
import os
import sys
import threading
import traceback

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "src"))
from sparkforge import server, api_v02, meta, acp, mcp_client  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


# ---- JAG-233: _send must serialize ANY json payload, incl. None ------------
class Sink:
    def __init__(self):
        self.code = None
        self.headers = []
        self.body = b""

        class _W:
            def __init__(self, s):
                self.s = s

            def write(self, b):
                self.s.body += b

        self.wfile = _W(self)

    def send_response(self, code):
        self.code = code

    def send_header(self, k, v):
        self.headers.append((k, v))

    def end_headers(self):
        pass


for payload, want in [(None, b"null"), (0, b"0"), (True, b"true"),
                      ("hi", b"hi"), (b"raw", b"raw"),
                      ({"a": 1}, b'"a"'), ([1], b"1")]:
    s = Sink()
    try:
        server.Handler._send(s, 200, payload)
        ok = s.code == 200 and want in s.body
        check("JAG-233 _send(%r) -> 200" % (payload,), ok, "body=%r" % s.body)
    except Exception as e:  # noqa: BLE001
        check("JAG-233 _send(%r) -> 200" % (payload,), False, repr(e))


# ---- JAG-234: candidate_label must never raise on a real candidate space ----
broken = {"model": None, "prompt_style": None, "tool_approval": None,
          "sandbox_backend": None, "max_steps": "x", "temperature": None}
try:
    lbl = meta.candidate_label(broken, 0)
    check("JAG-234 candidate_label(None-ish) -> str", isinstance(lbl, str), lbl)
except Exception as e:  # noqa: BLE001
    check("JAG-234 candidate_label(None-ish) -> str", False, repr(e))

try:
    lbl = meta.candidate_label({}, 1)
    check("JAG-234 candidate_label({}) -> str", isinstance(lbl, str), lbl)
except Exception as e:  # noqa: BLE001
    check("JAG-234 candidate_label({}) -> str", False, repr(e))

try:
    cands = meta.sample_candidates(n=8)
    labels = [meta.candidate_label(c, i) for i, c in enumerate(cands)]
    check("JAG-234 sample_candidates(8) all labelable",
          len(labels) == len(cands) and all(isinstance(x, str) for x in labels))
except Exception as e:  # noqa: BLE001
    check("JAG-234 sample_candidates(8) all labelable", False, repr(e))


# ---- JAG-235: run_get/run_control must reject non-string ids ---------------
for bad in ([1], {"a": 1}, None, 7):
    try:
        check("JAG-235 run_get(%r) -> None" % (bad,), api_v02.run_get(bad) is None)
    except Exception as e:  # noqa: BLE001
        check("JAG-235 run_get(%r) -> None" % (bad,), False, repr(e))
try:
    check("JAG-235 run_control([1],'abort') -> None",
          api_v02.run_control([1], "abort") is None)
except Exception as e:  # noqa: BLE001
    check("JAG-235 run_control([1],'abort') -> None", False, repr(e))


# ---- JAG-236: ACP connect validates wire types -----------------------------
mgr = acp.ACPClientManager()
for name, url in [(123, 999), ("ok", 999), (None, "http://x"), ("x", None),
                  ("", "http://x"), ("x", "")]:
    try:
        check("JAG-236 connect(%r,%r) -> False" % (name, url),
              mgr.connect(name, url) is False)
    except Exception as e:  # noqa: BLE001
        check("JAG-236 connect(%r,%r) -> False" % (name, url), False, repr(e))
try:
    c = acp.ACPClient("n", 999, {"bad": 1})
    check("JAG-236 ACPClient(int url) coerces base",
          c.base == "999" and c.token is None, "base=%r token=%r" % (c.base, c.token))
except Exception as e:  # noqa: BLE001
    check("JAG-236 ACPClient(int url) coerces base", False, repr(e))


# ---- JAG-237: disconnect_all is safe against a concurrent insert -----------
class FakeSess:
    def close(self):
        pass


m = mcp_client.MCPClientManager()
errors = []


def churn():
    try:
        for i in range(3000):
            m.disconnect_all()
    except Exception:  # noqa: BLE001
        errors.append(traceback.format_exc())


def inserter():
    try:
        for i in range(3000):
            with m._lock:
                m.sessions["s%d" % i] = FakeSess()
    except Exception:  # noqa: BLE001
        errors.append(traceback.format_exc())


ts = [threading.Thread(target=churn) for _ in range(3)] + \
     [threading.Thread(target=inserter) for _ in range(2)]
for t in ts:
    t.start()
for t in ts:
    t.join()
check("JAG-237 disconnect_all vs concurrent insert: no RuntimeError",
      not errors, errors[0][-160:] if errors else "")


# ---- static guards ---------------------------------------------------------
def read(rel):
    with open(os.path.join(REPO, "src", "sparkforge", rel), encoding="utf-8") as f:
        return f.read()


sv = read("server.py")
mv = read("meta.py")
av = read("api_v02.py")
acv = read("acp.py")
mcpv = read("mcp_client.py")
check("JAG-233 _send branches on str/bytes (json.dumps fallback)",
      "if isinstance(obj, bytes):" in sv and "elif isinstance(obj, str):" in sv)
check("JAG-234 candidate_label coerces model",
      '_txt(cand.get("model"), "default")' in mv)
check("JAG-235 run_get guards non-string rid",
      "if not isinstance(rid, str):" in av)
check("JAG-236 connect validates url type",
      "not isinstance(url, str)" in acv)
check("JAG-237 disconnect_all snapshots under lock",
      "list(self.sessions.values())" in mcpv)

print("---")
ok = sum(results)
print("%d/%d PASS" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)
