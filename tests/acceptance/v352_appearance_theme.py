#!/usr/bin/env python3
"""v352 — Appearance: theme switcher + compaction model in the chat model menu (JAG-352).

Static guards for the WebUI work:
  A) three themes exist (indigo/dark/sand) with real CSS token blocks;
  B) an Appearance settings category renders a swatch grid and persists the choice;
  C) the theme is applied PRE-PAINT (no flash);
  D) a "bolder text" preference exists;
  E) the chat model menu carries the compaction-model control and it is wired to
     POST /api/routing (summarizer) + loaded at boot.

Deterministic, no model/browser. Run: python3 tests/acceptance/v352_appearance_theme.py
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HTML = open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8").read()

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


# --- A: themes ---------------------------------------------------------------
check("A1 the three themes are defined", all(
    s in HTML for s in ('id: "indigo"', 'id: "dark"', 'id: "sand"')), "")
check("A2 the sabbia theme has a real token block",
      'html[data-theme="sand"]' in HTML and "--bg: #f4ead7" in HTML, "")
check("A3 the dark theme has a real token block",
      'html[data-theme="dark"]' in HTML and "--bg: #0b0d12" in HTML, "")
check("A4 the sand theme switches native controls to light",
      "color-scheme: light" in HTML, "")
check("A5 tinted hotspots are token-driven (menubg/hover/sel)",
      "--menubg:" in HTML and "var(--menubg)" in HTML and "var(--hover)" in HTML, "")

# --- B: Appearance settings + persistence -----------------------------------
check("B1 an Appearance settings category exists",
      '["appearance", "Appearance"]' in HTML, "")
check("B2 the swatch grid + applyTheme persist the choice",
      'id="themeGrid"' in HTML and "function applyTheme" in HTML
      and 'localStorage.setItem("sf_theme", id)' in HTML, "")
check("B3 settingsCategory wires the appearance panel",
      'else if (name === "appearance")' in HTML and "renderThemeGrid()" in HTML, "")

# --- C: pre-paint (no flash) ------------------------------------------------
check("C1 a boot script applies the saved theme before paint",
      'localStorage.getItem("sf_theme") || "indigo"' in HTML
      and "dataset.theme = t" in HTML, "")

# --- D: bolder text ---------------------------------------------------------
check("D1 a bolder-text preference exists",
      'html.bold-text body' in HTML and 'id="boldText"' in HTML
      and "function applyBold" in HTML, "")

# --- E: compaction model in the chat model menu -----------------------------
check("E1 the model menu renders the compaction bar",
      'class = "mm-bar"' in HTML or 'className = "mm-bar"' in HTML, "")
check("E2 selecting a model in compact mode pins the summarizer",
      "function chooseCompactionModel" in HTML
      and 'roles: { summarizer: { model: ref } }' in HTML, "")
check("E3 the current compaction ref is loaded",
      "function loadCompactionRef" in HTML, "")
check("E4 it is loaded at boot",
      "loadSkills(); loadCompactionRef();" in HTML, "")
check("E5 the model menu toggles chat <-> compaction",
      '_mmMode = "chat", _compactRef = ""' in HTML and "compact ? \"← chat models\"" in HTML, "")

print("---")
ok = sum(results)
print("%d/%d PASS" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)
