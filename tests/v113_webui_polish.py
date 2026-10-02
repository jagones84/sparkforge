#!/usr/bin/env python3
"""v0.9.19 acceptance — sessions by usage, tool cards with input/output, keys status (JAG-113)."""
import os
import sys
import tempfile
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
tmp = tempfile.mkdtemp(prefix="sf-polish-")
os.environ["SPARKFORGE_SESSIONS_DIR"] = os.path.join(tmp, "sessions")
os.environ["SPARKFORGE_DB"] = os.path.join(tmp, "events.db")
os.environ["SPARKFORGE_GRAPH_DIR"] = os.path.join(tmp, "graphs")
os.makedirs(os.environ["SPARKFORGE_SESSIONS_DIR"], exist_ok=True)
os.makedirs(os.environ["SPARKFORGE_GRAPH_DIR"], exist_ok=True)
sys.path.insert(0, REPO)

import providers as P  # noqa: E402
import server  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


# ---- R1: relative time -----------------------------------------------------
now = time.time()
check("R1 seconds -> 'ora'", server._rel_time(now - 20) == "ora", server._rel_time(now - 20))
check("R1b minutes", server._rel_time(now - 300) == "5 min", server._rel_time(now - 300))
check("R1c hours", server._rel_time(now - 7200) == "2 h", server._rel_time(now - 7200))
check("R1d days", server._rel_time(now - 200000) == "2 g", server._rel_time(now - 200000))
check("R1e missing -> empty", server._rel_time(None) == "", repr(server._rel_time(None)))

# ---- R2: sessions ordered by LAST USE, with an age label -------------------
a = server.get_or_create_session("sessA")
server.append_message(a, "user", "ciao A")
b = server.get_or_create_session("sessB")
server.append_message(b, "user", "ciao B")
# touch A LAST -> A must come first even though B was created later
a = server.load_session("sessA")
server.append_message(a, "assistant", "risposta recente")
lst = server.list_sessions()
check("R2 sessions expose updated + age",
      all(("updated" in s and "age" in s) for s in lst), str(lst[0] if lst else None))
check("R2b sorted by last use (A touched last)", lst and lst[0]["id"] == "sessA",
      str([s["id"] for s in lst]))
check("R2c age is a non-empty label", bool(lst and lst[0]["age"]), str(lst[0]["age"] if lst else ""))

# ---- T1: tool event payload carries args + output, truncated ---------------
e = server._tool_event("shell", True, args={"cmd": "ls"},
                       output="x" * 5000, exit_code=0, backend="host", inline=True)
check("T1 event has args as text", isinstance(e.get("args"), str) and "ls" in e["args"],
      str(e.get("args")))
check("T1b output truncated", isinstance(e.get("output"), str) and len(e["output"]) <= server.TOOL_EVENT_MAX,
      "len=%d" % len(str(e.get("output"))))
check("T1c keeps meta", e.get("exit_code") == 0 and e.get("backend") == "host")

# ---- K1: keys status lists env NAMES (never values) ------------------------
BASE = os.path.join(tmp, "providers.yaml")
LOCAL = os.path.join(tmp, "providers.local.yaml")
with open(BASE, "w", encoding="utf-8") as f:
    f.write('version: "1"\nproviders:\n'
            "  - id: cloud\n    kind: openai\n    base_url: https://api.example.com/v1\n"
            "    api_key_env: ACME_API_KEY\n    models:\n      - {id: m1}\n")
P.CONFIG = BASE
P.LOCAL_CONFIG = LOCAL
P._cache.update(ts=None, cfg=None)
os.environ["ACME_API_KEY"] = "super-secret-value"
ks = server.keys_status()
row = next((k for k in ks["keys"] if k["env"] == "ACME_API_KEY"), None)
check("K1 required key listed", row is not None, str(ks))
check("K1b set flag true", row and row["set"] is True, str(row))
check("K1c never returns the value",
      "super-secret-value" not in str(ks), "leaked!")
os.environ.pop("ACME_API_KEY", None)

total = len(results)
passed = sum(results)
print("\n==== %d/%d checks passed ====" % (passed, total))
sys.exit(0 if passed == total else 1)
