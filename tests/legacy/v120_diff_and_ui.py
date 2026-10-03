#!/usr/bin/env python3
"""v0.9.24 acceptance — native diff tool + UI fixes (JAG-120)."""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
tmp = tempfile.mkdtemp(prefix="sf-120-")
os.environ["SPARKFORGE_CONFIG_DIR"] = os.path.join(tmp, "cfg")
os.environ["SPARKFORGE_SESSIONS_DIR"] = os.path.join(tmp, "sessions")
os.environ["SPARKFORGE_DB"] = os.path.join(tmp, "events.db")
os.environ["SPARKFORGE_GRAPH_DIR"] = os.path.join(tmp, "graphs")
for k in ("cfg", "sessions", "graphs"):
    os.makedirs(os.path.join(tmp, k), exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from sparkforge import registry  # noqa: E402
from sparkforge import tools  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


# ---- D1: the diff tool is registered and auto-approved --------------------
spec = registry.tool_spec("diff")
check("D1 diff tool registered + enabled", bool(spec) and spec.get("enabled"),
      str(spec and spec.get("enabled")))
check("D1b diff decision is auto", registry.classify("diff", {})[0] == "auto",
      str(registry.classify("diff", {})))

# ---- D2: text action produces a unified diff ------------------------------
r = tools.execute("diff", {"action": "text", "text_a": "a\nb\nc\n", "text_b": "a\nB\nc\nd\n"})
check("D2 text diff ok + not identical", r.get("ok") and r.get("identical") is False, str(r.get("error")))
check("D2b counts added/removed", r.get("added") == 2 and r.get("removed") == 1,
      "added=%s removed=%s" % (r.get("added"), r.get("removed")))
check("D2c stdout is a unified diff", "-b" in r.get("stdout", "") and "+B" in r.get("stdout", ""),
      repr(r.get("stdout", "")[:60]))

# ---- D3: identical texts report identical ---------------------------------
r = tools.execute("diff", {"action": "text", "text_a": "same\n", "text_b": "same\n"})
check("D3 identical texts", r.get("ok") and r.get("identical") is True, str(r))

# ---- D4: file action honours the read roots -------------------------------
r = tools.execute("diff", {"action": "files", "a": "rules.py", "b": "rules.py"})
check("D4 file diff (same file) identical", r.get("ok") and r.get("identical") is True, str(r.get("error")))
r = tools.execute("diff", {"action": "files", "a": "rules.py", "b": "/etc/passwd"})
check("D4b path outside roots rejected", r.get("ok") is False, str(r.get("error")))

# ---- U: WebUI static ------------------------------------------------------
html = open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8").read()
check("U1 skills upload is above the skills list",
      html.find("Install from zip") < html.find("Skills · installed"), "")
check("U2 the inspector scrolls on its own (titles stay)",
      "#inspector { flex: 1; min-height: 0; overflow-y: auto" in html
      and '[data-col="context"]  { flex: 0 0 238px; width: 238px; border-left: 1px solid var(--line); border-right: 0; overflow: hidden' in html,
      "")
check("U3 config tab can change the approval policy",
      'data-ap="' in html and 'approval: next' in html, "")

total = len(results)
passed = sum(results)
print("\n==== %d/%d checks passed ====" % (passed, total))
sys.exit(0 if passed == total else 1)
