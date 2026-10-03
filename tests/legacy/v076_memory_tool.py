#!/usr/bin/env python3
"""v0.7.6 acceptance — agent memory tool + prompt policy (JAG-73).

Proves the gap is closed: the agent can now DELIBERATELY remember and recall
(before, the store was passive and never cited in the system prompt).
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
tmp = tempfile.mkdtemp(prefix="sf-mem-")
os.environ["SPARKFORGE_SESSIONS_DIR"] = os.path.join(tmp, "sessions")
os.environ["SPARKFORGE_DB"] = os.path.join(tmp, "events.db")
os.environ["SPARKFORGE_GRAPH_DIR"] = os.path.join(tmp, "graphs")
sys.path.insert(0, os.path.join(REPO, "src"))

from sparkforge import memory  # noqa: E402
memory.DATA_DIR = os.path.join(tmp, "memory")   # isolate from real data/
memory._vector_db = None

from sparkforge import registry  # noqa: E402
from sparkforge import server  # noqa: E402
from sparkforge import tools  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


check("M1 `memory` tool is declared in the registry schema",
      "memory" in registry.TOOL_SCHEMAS,
      "tools=%s" % sorted(registry.TOOL_SCHEMAS)[-4:])

store = tools.execute("memory", {"action": "store",
                                 "content": "JAG-73 test: the deploy host is dgx"})
check("M2 action=store persists a note", store.get("ok") is True, str(store)[:140])

recall = tools.execute("memory", {"action": "recall", "query": "deploy host dgx"})
check("M3 action=recall finds the stored note",
      recall.get("ok") is True and recall.get("count", 0) >= 1, str(recall)[:180])

recent = tools.execute("memory", {"action": "recent", "limit": 5})
check("M4 action=recent lists the newest notes",
      recent.get("ok") is True and recent.get("count", 0) >= 1, str(recent)[:120])

bad = tools.execute("memory", {"action": "store"})
check("M5 empty store is rejected", bad.get("ok") is False, str(bad)[:120])

sp = server._system_prompt({"id": None})
check("M6 the memory POLICY is cited in the system prompt",
      "persistent memory store" in sp and "memory{action:'store'" in sp,
      "len=%d" % len(sp))

print("\n==== %d/%d checks passed ====" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
