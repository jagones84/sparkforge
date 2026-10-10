#!/usr/bin/env python3
"""v229 — malformed input must degrade gracefully, never crash (JAG-229).

Two proven bugs, one class:

  * SERVER — `int(qs.get("since", 0))` and friends raised an unhandled
    ValueError on `?since=abc`, so the socket was reset instead of returning a
    clean response. `_int_arg()` / `_content_length()` now fall back to a safe
    default on ANY malformed value.
  * WEBUI — every numeric settings field used `+$("id").value`, so clearing a
    box (`+"" == 0`) or typing junk (`+"abc" == NaN`) silently corrupted the
    saved config. `numField(id, fallback)` coerces with a known default.

Deterministic, no network, no browser. Run:  python3 tests/v229_robustness.py
"""
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("LONGRUN_CONFIG_DIR", os.path.join(REPO, ".tmp-v229-cfg"))
sys.path.insert(0, os.path.join(REPO, "src"))
from longrun import server  # noqa: E402

HTML = os.path.join(REPO, "webui", "index.html")
with open(HTML, encoding="utf-8") as f:
    html = f.read()
with open(os.path.join(REPO, "src", "longrun", "server.py"), encoding="utf-8") as f:
    py = f.read()

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


# ---- _int_arg: the query-string parser ----
check("_int_arg valid", server._int_arg({"n": "7"}, "n", 0) == 7)
check("_int_arg junk -> default", server._int_arg({"n": "abc"}, "n", 42) == 42)
check("_int_arg empty -> default", server._int_arg({"n": ""}, "n", 42) == 42)
check("_int_arg missing -> default", server._int_arg({}, "n", 42) == 42)
check("_int_arg negative kept", server._int_arg({"n": "-3"}, "n", 0) == -3)
check("_int_arg float-string -> default", server._int_arg({"n": "1.5"}, "n", 9) == 9)

# ---- no unguarded int(qs.get(...)) may remain in the request surface ----
# NB: `_as_int(qs.get(...))` is the GUARDED form; a negative lookbehind excludes
# the "_as_int(" prefix (which otherwise contains the substring "int(").
check("no unguarded int(qs.get(",
      not re.search(r"(?<![A-Za-z0-9_])int\(qs\.get\(", py))
check("no unguarded int(self.headers",
      'int(self.headers.get' not in py.replace(
          'return int(self.headers.get("Content-Length") or 0)', ""))

# ---- WebUI numField helper + all numeric saves migrated ----
check("numField is defined", "function numField(id, fallback)" in html)
check("numField falls back on junk", "Number.isFinite(v) ? v : fallback" in html)
for ident in ("rtKgMax", "rtNoProg", "rtWall", "rtDepth", "vfTimeout", "bnN",
              "bnMin", "dfEasy", "dfMed", "dfHard", "dfMedAt", "dfHardAt",
              "seMinLen", "seMinCount", "seMaxLen"):
    check("settings save coerces " + ident, ('numField("%s"' % ident) in html)
check("no raw +$(...).value numeric save left", '+$("rt' not in html and
      '+$("vf' not in html and '+$("bn' not in html and '+$("df' not in html and
      '+$("seM' not in html)

print("---")
ok = sum(results)
print("%d/%d PASS" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)
