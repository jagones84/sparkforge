#!/usr/bin/env python3
"""v238 — a malformed stored transcript must never crash /api/context (JAG-238).

A client POSTed `{"message": 123}` to `/api/chat`; the int was persisted verbatim
and later `context_engine.count_tokens` did `len(int)` -> TypeError inside
`/api/context`, which dropped the connection. The WebUI `loadCtx` then kept the
PREVIOUS session's meter on screen, so a small chat appeared "saturated at 195%".

Also guards JAG-239: a live chaos test must not persist a real session.

Deterministic, no live server. Run:  python3 tests/v238_context_robustness.py
"""
import json
import os
import shutil
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_tmp = tempfile.mkdtemp(prefix="sf-238-")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(_tmp, "sessions")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(_tmp, "cfg")
os.makedirs(os.environ["LONGRUN_SESSIONS_DIR"], exist_ok=True)
os.makedirs(os.environ["LONGRUN_CONFIG_DIR"], exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))
from longrun import context_engine, server  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


# ---- JAG-238: count_tokens tolerates non-strings --------------------------
for val, want in [(None, 0), ("", 0), (123, 0), (123456, 0), ("abcd", 1)]:
    try:
        got = context_engine.count_tokens(val)
        check("count_tokens(%r) no-crash" % (val,), isinstance(got, int))
    except Exception as e:  # noqa: BLE001
        check("count_tokens(%r) no-crash" % (val,), False, repr(e))

try:
    n = context_engine._msgs_tokens([{"content": 123}, {"content": None},
                                     {"content": "hello"}])
    check("_msgs_tokens mixed content no-crash", isinstance(n, int), "n=%s" % n)
except Exception as e:  # noqa: BLE001
    check("_msgs_tokens mixed content no-crash", False, repr(e))

try:
    msgs, stats = context_engine.compact(
        [{"role": "user", "content": 99}, {"role": "assistant", "content": None}],
        budget_tokens=10, force=True)
    check("compact() with non-str content no-crash",
          isinstance(msgs, list) and isinstance(stats, dict))
except Exception as e:  # noqa: BLE001
    check("compact() with non-str content no-crash", False, repr(e))

# ---- JAG-238: /api/context survives a poisoned session ---------------------
poison = {"id": "v238poison", "title": "poison", "model": None, "workspace": None,
          "messages": [{"role": "user", "content": 123, "ts": 1.0},
                       {"role": "assistant", "content": "ok", "ts": 2.0}]}
with open(os.path.join(os.environ["LONGRUN_SESSIONS_DIR"], "v238poison.json"),
          "w", encoding="utf-8") as f:
    json.dump(poison, f)
try:
    c = server.context_usage("v238poison")
    check("context_usage(poisoned session) returns a dict",
          isinstance(c, dict) and c.get("available") is True,
          "used=%s pct=%s" % (c.get("tokens_used"), c.get("pct")))
except Exception as e:  # noqa: BLE001
    check("context_usage(poisoned session) returns a dict", False, repr(e))

# ---- JAG-238: append_message coerces content to str ------------------------
try:
    sess = {"id": "v238append", "messages": []}
    m = server.append_message(sess, "user", 123)
    check("append_message(123) stores a STRING", isinstance(m["content"], str),
          "content=%r" % m["content"])
except Exception as e:  # noqa: BLE001
    check("append_message(123) stores a STRING", False, repr(e))

# ---- static guards ---------------------------------------------------------
def read(rel):
    with open(os.path.join(REPO, "src", "longrun", rel), encoding="utf-8") as f:
        return f.read()


sv = read("server.py") + read("httpapi.py")
cev = read("context_engine.py")
with open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8") as f:
    ui = f.read()
with open(os.path.join(REPO, "tests", "live", "v208_chaos_http.py"),
          encoding="utf-8") as f:
    v208 = f.read()

check("count_tokens coerces non-str", "if not isinstance(text, str):" in cev)
check("/api/chat rejects a non-string message",
      'message must be a string' in sv)
check("append_message coerces content",
      "if not isinstance(content, str):" in sv)
check("WebUI loadCtx resets on error (no stale meter)",
      "ctxNa(\"n/d\")" in ui)
check("v208 chaos probes the 2MB body via a non-persisting route",
      'call("POST", "/api/context/preview"' in v208 and
      'json.dumps({"message": "x" * 2_000_000})' in v208)

shutil.rmtree(_tmp, ignore_errors=True)
print("---")
ok = sum(results)
print("%d/%d PASS" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)
