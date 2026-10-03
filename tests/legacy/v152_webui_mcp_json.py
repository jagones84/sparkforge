#!/usr/bin/env python3
"""SparkForge v0.15.2 acceptance — MCP JSON (configure-manually, Trae-style).

Checks (exit 0 = pass):
  J  a button exposes the final `mcpServers` JSON; the JSON can be edited and
     applied back (upsert) via POST /api/mcp/clients; copy + Esc wired.
"""
import os, sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ok = True
def check(name, cond, detail=""):
    global ok
    ok &= bool(cond)
    print(("PASS " if cond else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))

html = open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8").read()

check("J1 button opens the MCP JSON editor", "openMcpJson(" in html and "MCP JSON" in html)
check("J2 modal shell present", 'id="mcpJsonWin"' in html and 'id="mcpJsonText"' in html)
check("J3 serializes the final mcpServers JSON",
      "mcpServers" in html and "mcpClientsToJson" in html)
check("J4 imports/upserts via POST /api/mcp/clients",
      "applyMcpJson" in html and '"/api/mcp/clients"' in html and "async function applyMcpJson" in html)
check("J5 copy + Esc close wired",
      "copyMcpJson" in html and "navigator.clipboard" in html and "closeMcpJson" in html)

print("\n==== %d/%d checks passed ====" % (0, 0) if False else "")
print("RESULT:", "PASS" if ok else "FAIL")
sys.exit(0 if ok else 1)
