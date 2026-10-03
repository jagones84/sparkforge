#!/usr/bin/env python3
"""v0.9.20 acceptance — global/project rules + workspace selection (JAG-114)."""
import json
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
tmp = tempfile.mkdtemp(prefix="sf-rules-")
CFG = os.path.join(tmp, "cfg")
os.environ["SPARKFORGE_CONFIG_DIR"] = CFG
os.environ["SPARKFORGE_SESSIONS_DIR"] = os.path.join(tmp, "sessions")
os.environ["SPARKFORGE_DB"] = os.path.join(tmp, "events.db")
os.environ["SPARKFORGE_GRAPH_DIR"] = os.path.join(tmp, "graphs")
os.makedirs(CFG, exist_ok=True)
os.makedirs(os.environ["SPARKFORGE_SESSIONS_DIR"], exist_ok=True)
os.makedirs(os.environ["SPARKFORGE_GRAPH_DIR"], exist_ok=True)
WS = os.path.join(tmp, "proj")
os.makedirs(os.path.join(WS, ".sparkforge", "rules"), exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from sparkforge import api_v02  # noqa: E402
from sparkforge import rules as R  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


# ---- R1: global paths live under the config dir ---------------------------
check("R1 global rules path under config dir",
      R.global_rules_path() == os.path.join(CFG, "RULES.md"), R.global_rules_path())

# ---- R2: project rules = .sparkforge/RULES.md + rules/*.md (sorted) -------
write(os.path.join(WS, ".sparkforge", "RULES.md"), "PROJECT-NATIVE")
write(os.path.join(WS, ".sparkforge", "rules", "10-a.md"), "PROJECT-A")
write(os.path.join(WS, ".sparkforge", "rules", "20-b.md"), "PROJECT-B")
R.set_workspace(WS)
col = R.collect()
check("R2 workspace persisted", R.get_workspace() == WS, R.get_workspace())
check("R2b projects files collected (native + 2)",
      len(col["project"]["files"]) == 3, str(col["project"]["files"]))
check("R2c project text includes all three",
      all(x in col["project"]["text"] for x in ("PROJECT-NATIVE", "PROJECT-A", "PROJECT-B")),
      col["project"]["text"][:60])

# ---- R3: AGENTS.md compatibility ------------------------------------------
WS2 = os.path.join(tmp, "proj2")
os.makedirs(WS2, exist_ok=True)
write(os.path.join(WS2, "AGENTS.md"), "PROJECT-AGENTS-COMPAT")
R.set_workspace(WS2)
col2 = R.collect()
check("R3 project falls back to AGENTS.md",
      "PROJECT-AGENTS-COMPAT" in col2["project"]["text"], col2["project"]["text"][:40])
write(os.path.join(CFG, "AGENTS.md"), "GLOBAL-AGENTS-COMPAT")
check("R3b global falls back to AGENTS.md",
      "GLOBAL-AGENTS-COMPAT" in R.collect()["global"]["text"], R.collect()["global"]["text"][:40])

# ---- R4: block order (global first) + cap ---------------------------------
R.save("global", "GLOBAL-RULE-XYZ")
R.set_workspace(WS)
blk = R.rules_block()
check("R4 block has global before project",
      blk.find("GLOBAL-RULE-XYZ") >= 0 and blk.find("GLOBAL-RULE-XYZ") < blk.find("PROJECT-NATIVE"),
      "gi=%d pi=%d" % (blk.find("GLOBAL-RULE-XYZ"), blk.find("PROJECT-NATIVE")))
small = R.rules_block(max_bytes=20)
check("R4b block respects the cap", len(small) <= 40, "len=%d" % len(small))

# ---- R5: save is atomic + reflected ---------------------------------------
r5 = R.save("project", "SAVED-PROJECT-RULE")
check("R5 save ok", r5.get("ok") is True, str(r5))
check("R5b project RULES.md written and no .tmp left",
      os.path.isfile(R.project_rules_path()) and not os.path.exists(R.project_rules_path() + ".tmp"),
      R.project_rules_path())
check("R5c collect reflects the save",
      "SAVED-PROJECT-RULE" in R.collect()["project"]["text"], "")

# ---- R6: workspace switch changes project rules ---------------------------
R.set_workspace(WS2)
check("R6 switching workspace switches project rules",
      "PROJECT-AGENTS-COMPAT" in R.collect()["project"]["text"], "")

# ---- R7: additive AGENTS.md; only no files at all -> empty block ----------
# ADDITIVE contract (spec JAG-128A): a present-but-empty RULES.md no longer
# excludes the same scope's AGENTS.md, so the block must still carry its text.
R.save("global", "")
WS3 = os.path.join(tmp, "proj3")
os.makedirs(WS3, exist_ok=True)
R.set_workspace(WS3)
r7_additive = "GLOBAL-AGENTS-COMPAT" in R.rules_block()
# ...while a scope with NEITHER RULES.md NOR AGENTS.md stays empty.
os.remove(os.path.join(CFG, "AGENTS.md"))
os.remove(os.path.join(CFG, "RULES.md"))
r7_empty = R.rules_block() == ""
check("R7 empty RULES.md keeps AGENTS.md (additive); no files -> empty block",
      r7_additive and r7_empty,
      "additive=%s empty=%s" % (r7_additive, r7_empty))

# ---- A1: API helpers -------------------------------------------------------
check("A1 api helpers present",
      all(hasattr(api_v02, n) for n in ("rules_status", "rules_save",
                                        "workspace_get", "workspace_set")),
      str([n for n in ("rules_status", "rules_save", "workspace_get", "workspace_set")
           if not hasattr(api_v02, n)]))

total = len(results)
passed = sum(results)
print("\n==== %d/%d checks passed ====" % (passed, total))
sys.exit(0 if passed == total else 1)
