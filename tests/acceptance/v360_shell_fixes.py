#!/usr/bin/env python3
"""v360 — theme completeness, a click-proof handle, and a chat that can't be crushed (JAG-360).

Static guards only (deterministic, no model, no network):

  A) NO surface keeps the indigo look: no near-black popup grays, no bluish
     hover/active tints — every one resolves through a theme token, so Sand/Sepia
     re-paint the WHOLE UI (settings, popovers, MCP textarea, scrollbars);
  B) the panel handle toggles on POINTER UP with a movement guard, so a press and
     hold behaves exactly like a tap and a 1-2 px wobble cannot cancel the click;
  C) the centre column has a min-width floor and the side panels are shrinkable, so
     a wide panel (or a narrow window) can never crush the chat;
  D) the defaults are indigo + NO bolder text.

Run: python3 tests/acceptance/v360_shell_fixes.py
"""
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

with open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8") as f:
    HTML = f.read()

results = []


def check(name, cond, extra=""):
    ok = bool(cond)
    results.append(ok)
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(extra)) if extra else ""))


# --- A: no surface keeps the indigo look -------------------------------------
check("A1 no near-black popup gray is left hardcoded",
      "#0b0f18" not in HTML and "rgba(24,28,40" not in HTML, "")
check("A2 no bluish hover/active/chip tint is left as a background",
      re.search(r"background:\s*rgba\((?:108,140,255|120,140,255|139,123,240)", HTML) is None, "")
check("A3 those surfaces now resolve through theme tokens",
      "background: var(--menubg);" in HTML and "background: var(--hover);" in HTML
      and "background: var(--sel);" in HTML and "background: var(--scroll);" in HTML, "")
check("A4 the settings window itself paints with the theme token",
      "#settingsWin { position: fixed" in HTML and "background: var(--menubg);" in HTML, "")

# --- B: a click-proof handle -------------------------------------------------
check("B1 the handle toggles on pointer UP with a movement guard",
      'h.addEventListener("pointerup", e => {' in HTML
      and "Math.abs(e.clientX - x0) + Math.abs(e.clientY - y0) <= 8" in HTML, "")
check("B2 the pointer-up path calls the same toggles",
      '(id === "handle-left" ? toggleLeftPanel : toggleRightPanel)();' in HTML, "")
check("B3 the fragile native onclick is gone",
      '$("handle-left").onclick' not in HTML and '$("handle-right").onclick' not in HTML, "")
check("B4 the press guard against the resize grip is kept",
      'h.onmousedown = e => { e.preventDefault(); e.stopPropagation(); };' in HTML, "")

# --- C: the chat cannot be crushed -------------------------------------------
check("C1 the centre column has a min-width floor",
      '[data-col="chat"]     { flex: 1 1 auto; min-width: 420px;' in HTML, "")
check("C2 the side panels are shrinkable and have their own floor",
      'flex: 0 1 220px; width: 220px; min-width: 150px;' in HTML
      and 'flex: 0 1 238px; width: 238px; min-width: 150px;' in HTML, "")
check("C3 a saved width is restored shrinkable (never 0 0)",
      'col.style.flex = "0 1 " + saved + "px";' in HTML, "")
check("C4 the drag + the saved width use the CSS-px unit (page scale)",
      "col.getBoundingClientRect().width / z;" in HTML
      and "col.getBoundingClientRect().width / _pageScale()" in HTML, "")

# --- D: defaults -------------------------------------------------------------
check("D1 the default theme is indigo",
      'localStorage.getItem("sf_theme") || "indigo"' in HTML, "")
check("D2 the default is NO bolder text",
      HTML.count('(localStorage.getItem("sf_bold") || "0") === "1"') == 2, "")

print("---")
ok = sum(results)
print("%d/%d PASS" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)
