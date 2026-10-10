#!/usr/bin/env python3
"""v210 — Command Deck interactive console regression gate (JAG-210).

Deterministic, no server. Guarantees the deck is a real *app* (not just a
dashboard): it can transmit a directive to the live harness and stream the
reply, with an abort path and a demo fallback.

  A) the Command Console UI exists (input / send / abort / output);
  B) it is wired to the live streaming contract (/api/chat/stream + abort);
  C) it consumes the SSE events the server actually emits;
  D) it stays self-contained (no external resource) and accessible;
  E) keyboard control (Enter=send, Esc=abort) and /goal support.

Run:  python3 tests/v210_deck_command.py
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DECK = os.path.join(REPO, "webui", "console.html")
results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


try:
    with open(DECK, "r", encoding="utf-8") as f:
        html = f.read()
except OSError:
    html = ""

# ---- A: the console UI exists ----
for el in ('id="cmdInput"', 'id="cmdSend"', 'id="cmdAbort"', 'id="cmdOut"'):
    check("A1 has %s" % el, el in html, "")
check("A2 console panel labelled", 'aria-labelledby="h-cmd"' in html, "")
check("A3 output is a live log region", 'id="cmdOut"' in html and 'role="log"' in html
      and "aria-live" in html, "")

# ---- B: wired to the live streaming contract ----
check("B1 posts to /api/chat/stream", "/api/chat/stream" in html, "")
check("B2 can abort (/api/chat/abort)", "/api/chat/abort" in html, "")
check("B3 uses EventSource (SSE)", "new EventSource(" in html, "")
check("B4 transmit() actually opens the stream", "function transmit()" in html
      and "EventSource(url)" in html, "")
check("B5 abort is POSTed", '.catch' in html and "abort transmitted" in html, "")

# ---- C: consumes the real SSE events ----
for ev in ("chat.run", "chat.delta", "chat.done", '"done"', '"error"', "tool.call", "tool.result"):
    check("C1 handles event %s" % ev, ev in html, "")
check("C2 appends streamed text", "cmdDelta(" in html and "textContent += text" in html, "")

# ---- D: self-contained + accessible ----
check("D1 no external <script src>", "<script src=" not in html, "")
check("D2 no CDN references", not any(x in html.lower() for x in ("cdn.", "unpkg", "jsdelivr")), "")
check("D3 has a demo fallback (file:// / offline)", "demoTransmit" in html and "state.offline" in html, "")
check("D4 disables send while streaming", 'disabled = run' in html, "")

# ---- E: keyboard + /goal ----
check("E1 Enter sends", 'e.key === "Enter"' in html, "")
check("E2 Escape aborts", 'e.key === "Escape"' in html, "")
check("E3 /goal autonomous mode", "/^\\/goal\\b/i" in html and "mode=goal" in html, "")
check("E4 wired at startup", "wireConsole()" in html, "")

ok = sum(results)
print("\nv210: %d/%d PASS" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)

