#!/usr/bin/env python3
"""v0.9.38 acceptance — self-evolving miner di sequenze (JAG-133)."""
import json
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


import selfevolve  # noqa: E402

check("S1 defaults sane",
      selfevolve.DEFAULTS["min_len"] == 2 and selfevolve.DEFAULTS["min_count"] == 3, "")

seqs = [
    ["fs.read", "shell", "fs.edit", "shell"],
    ["fs.read", "shell", "fs.edit", "shell"],
    ["fs.read", "shell", "fs.edit", "shell"],
    ["web", "self"],
]
found = selfevolve.mine(seqs, {"min_len": 2, "min_count": 3, "max_len": 4})
top = found[0] if found else None
check("S2 repeated sequence found with support 3",
      top is not None and top["support"] == 3 and top["pattern"] == ["fs.read", "shell", "fs.edit", "shell"],
      str(top))
check("S3 a one-off sequence is not proposed",
      all("web" not in c["pattern"] for c in found), str(found))

# the longest pattern with the same run set wins over its sub-patterns
check("S4 only the longest pattern survives (dedup)",
      len(found) == 1 and found[0]["length"] == 4, str([c["pattern"] for c in found]))

check("S5 no proposal below min_count",
      selfevolve.mine([["a", "b"], ["a", "b"]], {"min_len": 2, "min_count": 3}) == [], "")

check("S6 slug is filesystem-safe",
      selfevolve.slug(["fs.read", "shell/../x"]) == "fs.read-shell-..-x", selfevolve.slug(["fs.read", "shell/../x"]))

tmp = tempfile.mkdtemp()
paths = selfevolve.scan(seqs, tmp, {"min_len": 2, "min_count": 3, "max_len": 4})
check("S7 scan writes one proposal folder", len(paths) == 1, str(paths))
if paths:
    with open(os.path.join(paths[0], "proposal.json"), encoding="utf-8") as f:
        prop = json.load(f)
    check("S8 proposal is status=proposed (never auto-archived)",
          prop["status"] == "proposed" and prop["kind"] == "skill"
          and prop["support"] == 3, str(prop))
    check("S9 SKILL.md draft written",
          os.path.isfile(os.path.join(paths[0], "SKILL.md")), "")

# history round-trip + mining from the recorded history (JAG-133)
datadir = tempfile.mkdtemp()
os.environ["SPARKFORGE_DATA_DIR"] = datadir
hp = os.path.join(datadir, "sequences.json")
for i in range(3):
    selfevolve.record("run%d" % i, ["git", "fs.edit", "shell", "git"], path=hp)
selfevolve.record("runX", ["web"], path=hp)
hist = selfevolve.history(hp)
check("S10 history round-trip", len(hist) == 4 and hist[0] == ["git", "fs.edit", "shell", "git"], str(hist))
mined = selfevolve.mine_history(tempfile.mkdtemp(), {"min_len": 2, "min_count": 3}, path=hp)
check("S11 mine_history proposes the repeated pattern",
      len(mined) == 1 and os.path.isfile(os.path.join(mined[0], "proposal.json")), str(mined))

tools_src = open(os.path.join(REPO, "tools.py"), encoding="utf-8", errors="replace").read()
reg = open(os.path.join(REPO, "registry.py"), encoding="utf-8", errors="replace").read()
srv2 = open(os.path.join(REPO, "server.py"), encoding="utf-8", errors="replace").read()
check("S12 improve tool exposes scope=mine + harness records sequences",
      'scope == "mine"' in tools_src and "selfevolve.mine_history" in tools_src
      and '"mine"' in reg and "_se.record(" in srv2, "")

print("\n==== %d/%d checks passed ====" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)