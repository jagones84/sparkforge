#!/usr/bin/env python3
"""v198 — skills/tools AWARENESS (deterministic, no model).

Proves the chat system prompt actually tells the model:
  A) WHICH tools it has (registry block) and that only enabled ones are callable;
  B) WHICH skills are installed (name + one-line description) and that the body
     loads on demand via the `skills` tool;
  C) that it must SCAN the list and LOAD a matching skill before solving;
  D) how it answers capability questions (from the prompt / `self`, not shell);
  E) how to reach MCP tools (<client>__<tool>).

Run:  python3 tests/v198_skills_tools_awareness.py
"""
import atexit
import os
import shutil
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
tmp = tempfile.mkdtemp(prefix="sf-198-")
atexit.register(lambda: shutil.rmtree(tmp, ignore_errors=True))
os.environ["SPARKFORGE_CONFIG_DIR"] = os.path.join(tmp, "cfg")
os.environ["SPARKFORGE_SESSIONS_DIR"] = os.path.join(tmp, "sessions")
os.environ["SPARKFORGE_DB"] = os.path.join(tmp, "events.db")
os.environ["SPARKFORGE_GRAPH_DIR"] = os.path.join(tmp, "graphs")
os.environ["SPARKFORGE_EDITS_DIR"] = os.path.join(tmp, "edits")
os.environ["SPARKFORGE_RUNS_DIR"] = os.path.join(tmp, "runs")
for d in ("cfg", "sessions", "graphs", "edits", "runs"):
    os.makedirs(os.path.join(tmp, d), exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from sparkforge import server as _srv  # noqa: E402
from sparkforge import registry, skills, tools  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


sp = _srv._system_prompt(None)

# ---- A: tools are declared ----
check("A1 prompt lists a tool registry", "Tool registry" in sp, "")
names = [t["name"] for t in registry.catalog()]
check("A2 a `self` tool exists (self-knowledge)", "self" in names, str(names)[:140])
check("A3 a `skills` tool exists", "skills" in names, str(names)[:140])
check("A4 registry block is non-empty", ("  - " in sp), "")

# ---- B: skills known WITHOUT a discovery round-trip ----
check("B1 skills policy present", "installed skill library" in sp, "")
sk = skills.list_skills()
check("B2 at least one skill installed", len(sk) > 0, "count=%d" % len(sk))
if sk:
    nm = sk[0]["name"]
    check("B3 prompt names installed skills", nm in sp, nm)
    check("B4 skills list carries name + description", "\u2014" in skills.skills_context(), "")
check("B5 skills are capped (bounded context)", len(skills.skills_context(max_chars=200)) <= 260, "")

# ---- C: the model is told to SCAN and LOAD a skill ----
check("C1 policy tells the model to SCAN the list", "SCAN" in sp, "")
check("C2 policy tells how to LOAD one", "LOAD it with the `skills` tool" in sp, "")

# ---- D: capability questions answered from the prompt / self ----
check("D1 capability rule present", "answer FROM YOUR PROMPT" in sp, "")
check("D2 self-summary documents MCP tool naming", "<client>__<tool>" in sp, "")

# ---- E: memory policy ----
check("E1 memory policy present", "set_core" in sp and "memory" in sp.lower(), "")

# ---- F: skills are SEARCHABLE (progressive discovery, JAG-198) ----
check("F1 policy advertises the search action", '"action":"search"' in sp, "")
hits = skills.search_skills("connect dgx spark", limit=5)
check("F2 keyword search returns ranked skills", len(hits) > 0, "hits=%s" % [h["name"] for h in hits])
check("F3 best hit matches the query", bool(hits) and "dgx" in hits[0]["name"], str(hits[:1]))
res = tools.execute("skills", {"action": "search", "query": "connect dgx spark"})
check("F4 the `skills` tool exposes action=search",
      isinstance(res, dict) and res.get("ok") and res.get("count", 0) >= 1,
      "count=%s" % (res.get("count") if isinstance(res, dict) else res))
bad = tools.execute("skills", {"action": "search"})
check("F5 search without a query fails gracefully",
      isinstance(bad, dict) and bad.get("ok") is False, str(bad)[:80])

print("\n==== %d/%d checks passed ====" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
