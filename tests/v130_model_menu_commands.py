#!/usr/bin/env python3
"""v0.9.31 acceptance — model menu (all providers + keyboard) & chat commands (JAG-127).

 M  the model selector lists EVERY provider's models (not only the DGX router),
    is searchable, and is keyboard-navigable (↑↓ · ⏎ · esc);
 C  the slash menu shows chat COMMANDS (/goal, /skills, /compact) before skills;
 G  the Plan panel's goal button uses the SAME path as /goal in chat (no second
    agent loop, no manual "plan only").
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "src"))

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


def read(path):
    try:
        return open(path, encoding="utf-8", errors="replace").read()
    except OSError:
        return ""


html = read(os.path.join(REPO, "webui", "index.html"))

# ---- M: model menu ---------------------------------------------------------
check("M1 menu built from all providers", "(d.providers || []).forEach" in html and "flat.push({" in html, "")
check("M2 ref persisted as <provider>:<model>", "ref: m.ref || (p.id + \":\" + m.id)" in html, "")
check("M3 searchable", 'id="modelSearch"' in html and "inp.oninput = () => renderModelMenu(inp.value)" in html, "")
check("M4 keyboard nav", "function modelKey" in html and 'e.key === "ArrowDown"' in html
      and 'e.key === "ArrowUp"' in html and 'e.key === "Enter"' in html, "")
check("M5 highlight painted + scrolled", "function paintModelHi" in html and "classList.toggle(\"hl\"" in html, "")
check("M6 selection helper", "function chooseModel" in html, "")

# ---- C: chat commands ------------------------------------------------------
check("C1 commands declared", "SLASH_COMMANDS" in html and 'cmd: "goal"' in html
      and 'cmd: "skills"' in html and 'cmd: "compact"' in html, "")
check("C2 commands rendered before skills", 'h.textContent = "commands"' in html and 'h.textContent = "skills"' in html, "")
check("C3 /skills opens the panel", 'openPanel("skills")' in html, "")
check("C4 /compact compacts", "compactNow()" in html and 'c.cmd === "compact"' in html, "")

# ---- G: plan panel uses the chat /goal path --------------------------------
check("G1 plan button sends /goal", "function planGoal" in html and 'send("/goal " + goal)' in html, "")
check("G2 the panel no longer has its own planning loop", "function genPlan" not in html
      and 'onclick="genPlan()"' not in html, "")
check("G3 panel explains the difference", "does the same thing: plan + execute autonomously" in html, "")

# ---- backend: provider refs exist -----------------------------------------
try:
    from sparkforge import providers  # noqa: E402
    cat = providers.catalog()
    refs = [m["ref"] for p in cat.get("providers", []) for m in p.get("models", [])]
    check("B1 catalogue exposes <provider>:<model> refs", len(refs) > 1 and all(":" in r for r in refs),
          "%d refs, e.g. %s" % (len(refs), refs[0] if refs else ""))
    check("B2 more than just the local dgx provider",
          len({p["id"] for p in cat.get("providers", [])}) > 1, "")
except Exception as e:  # noqa: BLE001
    check("B1 catalogue exposes refs", False, str(e))

total = len(results)
passed = sum(results)
print("\n==== %d/%d checks passed ====" % (passed, total))
sys.exit(0 if passed == total else 1)
