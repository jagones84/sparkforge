#!/usr/bin/env python3
"""SparkForge v0.15.4 acceptance — Trae-parity panels (Browser, Terminal, Memories).

Checks (exit 0 = pass):
  B  Browser panel: read the public web via the harness `web` tool (fetch/search)
  T  Terminal panel: run commands via the harness `shell` tool (approval-gated)
  R  Memories: persistent memory via /api/memory (stats, search, add)
"""
import os, sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ok = True
def check(name, cond, detail=""):
    global ok
    ok &= bool(cond)
    print(("PASS " if cond else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))

html = open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8").read()

check("B1 Browser inspector section", 'data-insp="browser"' in html and "function browserGo" in html)
check("B2 Browser uses the harness web tool",
      'tool: "web"' in html and '"/api/tools/call"' in html and "browserOut" in html and 'action: "search"' in html)

check("T1 Terminal inspector section", 'data-insp="terminal"' in html and "function termRun" in html)
check("T2 Terminal uses the harness shell tool",
      'tool: "shell"' in html and "termLog" in html and "termInp" in html)

check("R1 Memories wired to /api/memory",
      "function loadMemories" in html and '"/api/memory"' in html and "function memoryAdd" in html)
check("R2 Memories rendered in the Rules category",
      'id="memList"' in html and 'id="memKind"' in html and 'id="memContent"' in html and "memStats" in html)

print("RESULT:", "PASS" if ok else "FAIL")
sys.exit(0 if ok else 1)
