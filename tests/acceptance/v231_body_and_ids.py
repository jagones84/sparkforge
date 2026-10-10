#!/usr/bin/env python3
"""v231 — wire-type robustness: non-object JSON bodies + non-int numeric fields (JAG-231).

Three proven bugs of the same family (untrusted wire data):

  * POST with a valid-JSON but non-OBJECT body (`[1,2]`, `"x"`, `42`, `true`,
    `null`) — every handler does `body.get(...)` -> AttributeError -> the
    connection was dropped with NO response. `_body()` now returns {} unless the
    parsed value is a dict.
  * `int(qs.get("limit", 50))` / `int(body.get("max_steps", 6))` in api_v02.py
    (13 sites) and `/api/agent/run`, `/api/eval/run` — `?limit=abc` raised an
    unhandled ValueError -> connection reset. Now `_int()` / `_as_int()`.
  * `improve._path(pid)` did `pid + ".json"`: a non-string pid (from
    `/api/improve {id:123}`) raised TypeError -> connection reset, and a
    traversal-shaped pid could escape the proposals store. `_path()` now rejects
    anything that is not a plain token.

Deterministic, isolated, no network. Run:  python3 tests/v231_body_and_ids.py
"""
import atexit
import os
import re
import shutil
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_tmp = tempfile.mkdtemp(prefix="sf-231-")
atexit.register(lambda: shutil.rmtree(_tmp, ignore_errors=True))
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(_tmp, "sessions")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(_tmp, "cfg")
os.environ["LONGRUN_DB"] = os.path.join(_tmp, "events.db")
sys.path.insert(0, os.path.join(REPO, "src"))
from longrun.core import server  # noqa: E402
from longrun.core import api_v02  # noqa: E402
from longrun.model import providers  # noqa: E402
from longrun.util import improve  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


# ---- safe int coercion helpers ----
check("server._as_int junk -> default", server._as_int("abc", 7) == 7)
check("server._as_int valid", server._as_int("6", 1) == 6)
check("server._as_int None -> default", server._as_int(None, 3) == 3)
check("api_v02._int junk -> default", api_v02._int("abc", 9) == 9)
check("api_v02._int float-string -> default", api_v02._int("1.5", 9) == 9)
check("providers._to_int('128k') -> 0", providers._to_int("128k") == 0)
check("providers._to_int('4096') -> 4096", providers._to_int("4096") == 4096)
check("providers._to_int(None) -> 0", providers._to_int(None) == 0)

# ---- improve._path: reject non-token / non-string pids ----
def raises(fn):
    try:
        fn()
        return False
    except ValueError:
        return True


check("improve._path valid pid ok", improve._path("1700000000000-project").endswith(".json"))
for bad in (123, None, "../x", "a/b", "a\\b", "", "a" * 81):
    check("improve._path rejects %r" % bad, raises(lambda b=bad: improve._path(b)))
check("get_proposal(int) -> None (no crash)", improve.get_proposal(123) is None)
check("get_proposal traversal -> None", improve.get_proposal("../../x") is None)
check("decide(int id) -> clean error dict",
      (improve.decide(123, "approve") or {}).get("ok") is False)

# ---- _body() must yield {} for a non-object JSON body (static guard) ----
with open(os.path.join(REPO, "src", "longrun", "core/server.py"), encoding="utf-8") as f:
    py = f.read()
with open(os.path.join(REPO, "src", "longrun", "core/httpapi.py"), encoding="utf-8") as f:
    py += f.read()
check("_body returns a dict only",
      "return parsed if isinstance(parsed, dict) else {}" in py)

# ---- no unguarded int(qs.get/int(body.get may remain in api_v02 ----
av = os.path.join(REPO, "src", "longrun", "core/api_v02.py")
with open(av, encoding="utf-8") as f:
    src = f.read()
offenders = []
for ln in src.splitlines():
    s = ln.strip()
    # skip comments and docstring/prose lines (they mention the pattern in prose)
    if s.startswith("#") or "`" in s:
        continue
    # a NEGATIVE lookbehind excludes the guarded `_int(qs.get(...)` form
    if re.search(r"(?<![A-Za-z0-9_])int\((?:qs|body)\.get\(", s):
        offenders.append(s)
check("api_v02 has no unguarded int(qs.get/body.get", not offenders, "; ".join(offenders)[:120])

print("---")
ok = sum(results)
print("%d/%d PASS" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)

