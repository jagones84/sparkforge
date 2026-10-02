#!/usr/bin/env python3
"""v0.9.35 acceptance — avviso 'piano incompleto' a fine turno (JAG-127f).

 A  a fine turno il chat loop calcola i nodi APERTI del task graph e pubblica
    l'evento `plan.incomplete` (nessuna chiamata LLM extra, nessun auto-continua).
 U  la WebUI mostra il banner con i passi aperti e il pulsante 'continua'.
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


def read(p):
    try:
        return open(p, encoding="utf-8", errors="replace").read()
    except OSError:
        return ""


srv = read(os.path.join(REPO, "server.py"))
html = read(os.path.join(REPO, "webui", "index.html"))

check("A1 server publishes plan.incomplete", 'publish("plan.incomplete"' in srv, "")
check("A2 open nodes computed from the task graph",
      'taskgraph.load(sess["id"])' in srv and '"done", "cancelled"' in srv, "")
check("A3 the event carries open/total/items",
      "open=len(" in srv and "items=" in srv, "")
check("A4 it is a warning, not an auto-continue (harness never sends the nudge)",
      "Continua: completa i passi aperti" not in srv, "")

check("U1 WebUI listens for plan.incomplete", 'addEventListener("plan.incomplete"' in html, "")
check("U2 a banner with a 'continua' button",
      "function planIncomplete" in html and "▶ continua" in html, "")
check("U3 the button resumes via send()", "Continua: completa i passi aperti" in html, "")
check("U4 styled warning", ".planwarn" in html or "plan-incomplete" in html, "")

total = len(results)
print("\n==== %d/%d checks passed ====" % (sum(results), total))
sys.exit(0 if all(results) else 1)
