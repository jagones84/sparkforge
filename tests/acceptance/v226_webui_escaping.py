#!/usr/bin/env python3
"""v226 — the WebUI must escape model/graph-controlled text inside innerHTML.

Regression for a proven XSS (JAG-226): a crafted `tool.call` name and an
`agent.thought` payload executed JavaScript (verified in-browser: window.__pwn=1
and two <img> injected into #log). toolCard(), the agent thought/tool lines,
showNodeDetail() and the "finished" toast all interpolated that text into
innerHTML unescaped. `esc()` (escaping & < > " ') is now applied at each site.

This is a static guard: it fails if any of those exact dangerous templates ever
comes back. Deterministic, no browser. Run:  python3 tests/v226_webui_escaping.py
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HTML = os.path.join(REPO, "webui", "index.html")

with open(HTML, encoding="utf-8") as f:
    src = f.read()

results = []


def check(name, ok):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name)


# esc() exists and neutralises the attribute-break-out chars (incl. quotes)
check("esc() is defined", "function esc(s)" in src)
check("esc() escapes the double quote (attribute break-out)", '&quot;' in src)
check("esc() escapes the single quote (attribute break-out)", "&#39;" in src)

# the exact dangerous templates must be GONE
check("toolCard data-tool= is escaped", 'data-tool="${name}"' not in src)
check("toolCard tool-name text is escaped",
      '<span class="tc-name">${name}</span>' not in src)
check("agent.thought escapes action + thought",
      "esc(d.action)" in src and "esc((d.thought" in src)
check("tool.call line escapes the tool name", "${esc(d.tool)}" in src)
check("showNodeDetail escapes the evidence text", "${esc(ev)}" in src)
check("finished-toast escapes the session title", 'esc(name || "session")' in src)
check("approvals panel escapes tool name + summary",
      "${esc(a.tool)}" in src and "${esc(a.summary)}" in src)
check("renderProviders escapes provider name/base_url/model id",
      '${p.base_url || ""}' not in src and "${esc(p.name || p.id" in src)

print("---")
ok = sum(1 for r in results if r)
print("%d/%d PASS" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)

