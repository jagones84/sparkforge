#!/usr/bin/env python3
"""SparkForge v0.12.3 acceptance — English UI strings + Ctrl+Enter composer.

Evidence, not claims. Checks on webui/index.html:

  A. the chat composer is a <textarea> (Enter inserts a newline, Ctrl/Cmd+Enter
     sends) — placeholder documents the shortcut.
  B. the Graph panel labels are distinct and English.
  C. no Italian UI tokens remain in the file (curated word list).

Usage: python3 tests/v123_ui_english.py
Exit code 0 iff every check passed.
"""
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HTML = os.path.join(REPO, "webui", "index.html")

RESULTS = {"task": "JAG-121c English UI + Ctrl+Enter", "checks": [], "passed": False}

ITALIAN = (r"\b(il|lo|la|le|gli|dei|delle|degli|della|dello|che|non|pi\u00f9|sono|viene|"
           r"stato|essere|questo|questa|questi|queste|dal|dalla|nel|nella|sul|sulla|alla|"
           r"allo|alle|premi|invio|apri|chiudi|cerca|crea|nuovo|nuova|senza|locale|modello|"
           r"modelli|imposta|rimuovi|mancante|obbligatorio|errore|caricamento|annulla|"
           r"cancella|sessione|cartella|sfoglia|salva|installa|progetto|globali|segreti|"
           r"percorso|regole|vuote|compatta|pannello|valori|titolo|conferma|blocca|"
           r"politica|esiste|valido)\b")


def check(name, ok, detail=""):
    RESULTS["checks"].append({"name": name, "ok": bool(ok), "detail": str(detail)[:400]})
    print("%s %s %s" % ("PASS" if ok else "FAIL", name, detail))
    return bool(ok)


def main():
    ok = True
    with open(HTML, "r", encoding="utf-8") as f:
        html = f.read()

    # A. composer
    ok &= check("A1 composer is a <textarea>", '<textarea id="inp"' in html)
    ok &= check("A2 Ctrl/Cmd+Enter sends", "e.ctrlKey || e.metaKey" in html)
    ok &= check("A3 placeholder documents Ctrl+Enter",
                "Ctrl+Enter to send" in html)
    ok &= check("A4 no plain-Enter send left",
                'if (e.key === "Enter") send();' not in html)

    # B. headings
    ok &= check("B1 'Plan \u00b7 session task list' heading",
                "Plan <span class=\"remaining\">\u00b7 session task list" in html)
    ok &= check("B2 'Execution \u00b7 run graph' heading",
                "Execution <span id=\"taskCount\"" in html)

    # C. no Italian left
    hits = sorted(set(m.group(0) for m in re.finditer(ITALIAN, html, re.I)))
    ok &= check("C1 no Italian UI tokens", not hits, hits)

    RESULTS["passed"] = bool(ok)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
