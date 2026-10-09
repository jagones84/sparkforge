#!/usr/bin/env python3
"""v368 — Resizing the side panels: mouse AND touch, columns AND drawers (JAG-368).

Locked here:
  * the border grip runs on POINTER events, so a FINGER works, not just a mouse
    (before this a phone could not resize a panel at all);
  * the grip has `touch-action:none` and out-stacks the circular collapse handle —
    the handle is centred ON the border and its mousedown called stopPropagation,
    so pressing the border at its centre was swallowed by the handle and the border
    never moved (it toggled the panel instead);
  * a panel that is a fixed DRAWER (narrow layout) is resized through a CSS var, with
    a grip glued to its inner edge (positionDrawerResizers);
  * the panel clamps account for the open editor dock (_dockRoomW), and opening or
    closing the dock re-fits the panels (editor.js _notifyLayout -> _settleHandles);
  * the dock itself can never grow so wide that it shoves the inspector off the right
    edge (JAG-369): only the collapse arrows may hide a panel, a resize must not.
Deterministic, no browser. Run: python3 tests/acceptance/v368_panel_resize.py
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
with open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8") as f:
    HTML = f.read()
with open(os.path.join(REPO, "webui", "assets", "editor.js"), encoding="utf-8") as f:
    EDITOR = f.read()

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


# --- A: the grip is pointer-driven (mouse + touch + pen) ----------------------
check("A1 the border grip runs on POINTER events (mouse + finger + pen)",
      'handle.addEventListener("pointerdown", e => {' in HTML
      and 'document.addEventListener("pointermove", move);' in HTML
      and 'document.addEventListener("pointerup", up);' in HTML
      and 'document.addEventListener("pointercancel", up);' in HTML, "")
check("A2 the grip turns off browser touch scrolling on itself",
      'position: relative; z-index: 31; touch-action: none;' in HTML, "")
check("A3 the grip out-stacks the circular collapse handle (no swallowed press)",
      '.edge-handle { position: fixed; top: 50%; z-index: 30;' in HTML, "")
check("A4 the press is captured so a fast drag off the 5px border still tracks",
      'handle.setPointerCapture(e.pointerId)' in HTML, "")

# --- B: a fixed DRAWER is resizable too ---------------------------------------
check("B1 a fixed DRAWER is resized through a CSS var (own width, not the column's)",
      "function _drawerVar(key)" in HTML and '"--drawer-w-left"' in HTML
      and '"--drawer-w-right"' in HTML
      and 'document.documentElement.style.setProperty(_drawerVar(key), w + "px")' in HTML, "")
check("B2 a drawer grip is glued to the drawer's inner edge",
      "function positionDrawerResizers()" in HTML
      and 's.el.style.left = Math.round(s.side === "left" ? r.right : r.left) + "px";' in HTML, "")
check("B3 each drawer carries a resizable width + a shown grip",
      'width: var(--drawer-w-right, 300px) !important' in HTML
      and 'body.show-right #resize-right { display: block !important; position: fixed;' in HTML
      and 'width: var(--drawer-w-left, 260px) !important' in HTML
      and 'body.show-left #resize-left { display: block !important; position: fixed;' in HTML, "")
check("B4 a drawer resize is persisted on its own key",
      'localStorage.setItem(key + "_d", String(Math.round(w)));' in HTML
      and 'localStorage.getItem(key + "_d")' in HTML, "")
check("B5 a fixed drawer is not treated as a layout column by the fit maths",
      'getComputedStyle(el).position !== "fixed"' in HTML, "")

# --- C: the editor dock is part of the row budget -----------------------------
check("C1 the panel clamp accounts for the open editor dock",
      "function _dockRoomW(z)" in HTML
      and "avail - ow - CHAT_MIN_W - _dockRoomW(z)" in HTML
      and "over = (lw + rw) - (avail - CHAT_MIN_W - _dockRoomW(z))" in HTML, "")
check("C2 opening/closing the dock re-fits the panels",
      "function _notifyLayout()" in EDITOR and "window._settleHandles" in EDITOR
      and EDITOR.count("_notifyLayout();") == 3, "")

# --- D: the dock can NEVER shove the inspector off-screen (JAG-369) ------------
# The dock is `flex: 0 0 auto`, so the flex algorithm never shrinks it. Dragging its
# left edge wider than the room the two panels + the chat floor leave over-constrains
# the row: it overflows to the RIGHT and #rail is pushed out of the viewport (clipped),
# looking like the inspector vanished. Only the collapse arrows may hide a panel.
check("D1 the app caps the dock by the room the panels + chat floor leave",
      "function _dockMaxW()" in HTML
      and "avail - side - CHAT_MIN_W" in HTML
      and "window._dockMaxW = _dockMaxW;" in HTML, "")
check("D2 the dock drag is bounded by that cap (not only the viewport)",
      "function _dockMaxW()" in EDITOR
      and "const cap = Math.min(_vw() - 120, _dockMaxW());" in EDITOR
      and "Math.min(cap, Math.max(320," in EDITOR, "")
check("D3 releasing the dock resize re-fits the panels",
      "if (dragging) { dragging = false; _notifyLayout(); }" in EDITOR, "")
check("D4 a restored dock width is clamped on (re)build and on every responsive pass",
      "Math.min(saved, _dockMaxW())" in EDITOR
      and EDITOR.count("_dockMaxW()") >= 4, "")
check("D5 the fit maths also caps an already-too-wide dock (self-heal on resize/zoom)",
      "dk.getBoundingClientRect().width / z > cap + 0.5" in HTML
      and "dk.style.width = Math.round(cap)" in HTML, "")

print("---")
ok = sum(results)
print("%d/%d PASS" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)
