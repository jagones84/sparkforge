#!/usr/bin/env python3
"""SparkForge v0.15.8 acceptance — topbar/editor UX, PMCP optional, Harness category (JAG-159).

Checks (exit 0 = pass):
  F*  inspector order: Feed moved to the bottom; settings gear gets a blue border
  P*  command palette no longer lists skills (sessions + MCP only)
  E*  editor: right-click copy-path menu + drag&drop temp tabs
  M*  PMCP is optional: conditional system prompt, generic tracked config, test skips
  H*  Settings: new "Harness" category; tool policy kept separate; archify restyle
  L*  live: /api/tools still serves runtime + verifier + difficulty
"""
import json
import os
import sys
import urllib.request

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ok = True


def check(name, cond, detail=""):
    global ok
    ok &= bool(cond)
    print(("PASS " if cond else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


def read(rel):
    p = os.path.join(REPO, rel)
    q = os.path.join(REPO, "src", "sparkforge", rel)
    if not os.path.dirname(rel) and os.path.isfile(q):
        p = q
    elif not os.path.isfile(p) and os.path.isfile(q):
        p = q
    return open(p, encoding="utf-8").read()


html = read(os.path.join("webui", "index.html"))
edj = read(os.path.join("webui", "assets", "editor.js"))
srv = read("server.py")
yaml = read(os.path.join("config", "mcp_clients.yaml"))

# ---- F: inspector order + settings gear ----
order = [html.index('data-insp="%s"' % k) for k in
         ("plan", "context", "approvals", "files", "browser", "terminal", "feed")]
check("F1 Feed is the last inspector section", order[-1] == max(order) and order.index(max(order)) == 6)
check("F2 terminal comes before feed", html.index('data-insp="terminal"') < html.index('data-insp="feed"'))
check("F3 settings gear has a blue accent border",
      "#settingsBtn { border-color: rgba(108,140,255,.55)" in html)

# ---- P: palette without skills ----
pstart = html.index("function loadPaletteDynamic")
pend = html.index("\nfunction ", pstart + 10)
palbody = html[pstart:pend]
check("P1 palette dynamic loader has no /api/skills", "/api/skills" not in palbody)
# JAG-160: the per-MCP-server entries were dropped; only sessions stay dynamic
# (the generic "Settings > MCP" item is the single MCP entry point).
check("P2 palette lists sessions but no per-MCP entries",
      "/api/sessions" in palbody and "/api/mcp/clients" not in palbody)

# ---- E: editor context menu + drag&drop ----
check("E1 right-click menu helpers",
      all(x in edj for x in ["function showTreeMenu", "function hideTreeMenu", "function copyPath"]))
check("E2 copy-path wired to file rows", "oncontextmenu" in edj and "showTreeMenu(e.clientX" in edj)
check("E3 drag&drop drop handlers", "function handleDrop" in edj and "function openTemp" in edj
      and "function openTempImage" in edj)
check("E4 temp tabs are not persisted", "state.tabs.filter((t) => !t.temp)" in edj)
check("E5 context menu + drop styles", "#edCtx{" in edj and "#editorDock.ed-drop" in edj
      and ".ed-tab .tmp" in edj)

# ---- M: PMCP optional ----
check("M1 conditional system prompt", "PMCP_PROMPT" in srv and "def system_prompt()" in srv
      and '"pmcp" in' in srv)
check("M2 all prompt call sites go through system_prompt()", srv.count("system_prompt()") >= 4,
      srv.count("system_prompt()"))
check("M3 tracked MCP config is generic", "clients: {}" in yaml and "\n  pmcp:" not in yaml)
check("M4 pmcp-dependent tests degrade to SKIP",
      all("def skip" in read(os.path.join("tests", f)) or "SKIP" in read(os.path.join("tests", f))
          for f in ("v07_mcp_fsedit.py", "v071_skills_pmcp.py", "v072_tool_use_acceptance.py")))

# ---- H: Harness category ----
check("H1 harness category + tool policy labels",
      'data-cat="harness"' in html and '["harness", "Harness"]' in html
      and '["tools", "Tool policy"]' in html)
check("H2 old combined label is gone", "Tools &amp; policy" not in html)
hstart = html.index('<div class="sw-cat" data-cat="harness"')
hblock = html[hstart:html.index('<div class="sw-cat" data-cat="tools"', hstart)]
check("H3 the 5 harness cards moved to Harness",
      all(x in hblock for x in ['id="rtKgMax"', 'id="vfOn"', 'id="bnOn"', 'id="dfOn"', 'id="seMinLen"']))
tstart = html.index('<div class="sw-cat" data-cat="tools"')
tblock = html[tstart:tstart + 400]
check("H4 tool policy keeps the live config panel",
      'id="configPanel"' in tblock and 'id="rtKgMax"' not in tblock)
check("H5 loaders split: harness vs tools",
      'else if (name === "harness") {' in html and 'loadRuntime(); loadVerifier(); loadBestofn();' in html
      and html.index('name === "harness"') < html.index('api("GET", "/api/tools").then(d => renderTools'))
check("H6 archify-based card restyle",
      ".hcard-hd" in html and ".hcard-hd .dot" in html and "--hc:" in html)

# ---- K: keys settable + official GitHub MCP (JAG-161) ----
srv2 = read("server.py")
api2 = read("api_v02.py")
gitignore = read(".gitignore")
check("K1 Keys panel can SET a value", "function setKey" in html and 'api("POST", "/api/keys"' in html)
check("K2 backend setter + route",
      "def set_key" in srv2 and "_env_file_upsert" in srv2 and 'path == "/api/keys"' in api2)
check("K3 GITHUB_TOKEN is a known key", '"GITHUB_TOKEN"' in srv2 and "KNOWN_ENV_KEYS" in srv2)
check("K4 repo .env is gitignored", "\n.env\n" in gitignore or gitignore.startswith(".env"))
check("K5 GitHub preset is the official remote server",
      "https://api.githubcopilot.com/mcp/" in html and "${GITHUB_TOKEN}" in html
      and "@modelcontextprotocol/server-github" not in html)

# ---- L: live (optional) ----
base = os.environ.get("SPARKFORGE_URL", "")
tok = os.environ.get("SPARKFORGE_TOKEN", "")
if base and tok:
    def req(method, path, body=None):
        data = json.dumps(body).encode() if body is not None else None
        r = urllib.request.Request(base + path, data=data, method=method,
                                   headers={"Authorization": "Bearer " + tok,
                                            "Content-Type": "application/json"})
        with urllib.request.urlopen(r, timeout=25) as resp:
            return json.loads(resp.read().decode())
    try:
        d = req("GET", "/api/tools")
        check("L1 /api/tools serves the harness runtime", isinstance(d.get("runtime"), dict), str(type(d.get("runtime"))))
        check("L2 /api/tools serves verifier + difficulty",
              isinstance(d.get("verifier"), dict) and isinstance(d.get("difficulty"), dict))
        check("L3 tool policy list present", isinstance(d.get("tools"), list) and len(d.get("tools")) > 0,
              len(d.get("tools") or []))
    except Exception as e:  # noqa: BLE001
        check("L live /api/tools", False, repr(e))
else:
    print("SKIP L* (set SPARKFORGE_URL + SPARKFORGE_TOKEN for the live checks)")

print("RESULT:", "PASS" if ok else "FAIL")
sys.exit(0 if ok else 1)
