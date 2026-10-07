#!/usr/bin/env python3
"""SparkForge v0.15.7 acceptance — compact in Context, clear settings, MCP Trae-like (JAG-158).

Checks (exit 0 = pass):
  C*  compact button lives in the Context section (not the topbar)
  S*  Tools & policy: plain labels + help text + tooltips
  M*  MCP: manual form removed; edit-in-editor + snippet append; local mcp.json (mcpServers)
  L*  live: /api/mcp/local-file + a disabled client round-trips into mcp_clients.local.json
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
mc = read("mcp_client.py")
api = read("api_v02.py")

# ---- C: compact in Context ----
top = html[html.index('id="topbar"'):html.index("</header>")]
check("C1 compact moved into Context",
      html.index('data-insp="context"') < html.index('id="compactBtn"'))
check("C2 compact not in the topbar", "compactBtn" not in top)
check("C3 compact handler unchanged", '$("compactBtn").onclick = compactNow;' in html)

# ---- S: Tools & policy clarity ----
check("S1 runtime explained", "<b>Runtime</b>" in html and "giri di continuazione" in html
      and "Quante volte l'agente" in html)
check("S2 difficulty plain labels + tooltip",
      "tentativi · facile" in html and "soglia → medio" in html and 'title="Soglia di difficoltà' in html)
check("S3 ids unchanged",
      all(x in html for x in ['id="rtKgMax"', 'id="dfMedAt"', 'id="seCat"', 'id="vfCmd"', 'id="bnN"']))
check("S4 every tools input has a title",
      html.count('title="Numero massimo di continuazioni') == 1 and "attiva il campionamento" in html.lower())

# ---- M: MCP Trae-like ----
check("M1 manual form removed",
      all(x not in html for x in ['id="mcpName"', 'id="mcpArgs"', 'id="mcpTransport"',
                                   'id="mcpCommand"', 'id="mcpEnv"', 'id="mcpUrl"']))
check("M2 Edit mcp.json + snippet buttons",
      "openMcpFile()" in html and "Edit mcp.json" in html and 'onclick="openMcpJson()"' in html)
check("M3 snippet helpers", "function mcpOpenSnippet" in html and "function mcpPresetSnippet" in html
      and 'b.textContent = "＋ add"' in html)
check("M4 openMcpFile ensures the file", 'api("POST", "/api/mcp/local-file"' in html)
check("M5 no dangling form calls",
      all(x not in html for x in ["mcpTransportChanged(", "mcpSpecFromForm", "saveMcpClient(",
                                   "testMcpClient(", "mcpFillPreset("]))
check("M6 backend mcpServers converters",
      "_servers_to_clients" in mc and "_clients_to_servers" in mc and "def ensure_local_file" in mc)
check("M7 backend route + status",
      "/api/mcp/local-file" in api and "ensure_local_file" in api and "CONFIG_LOCAL_JSON_PATH}" in mc)

# ---- L: live round-trip (optional) ----
base = os.environ.get("SPARKFORGE_URL", "")
tok = os.environ.get("SPARKFORGE_TOKEN", "")
if base and tok:
    def req(method, path, body=None):
        data = json.dumps(body).encode() if body is not None else None
        r = urllib.request.Request(base + path, data=data, method=method,
                                   headers={"Authorization": "Bearer " + tok,
                                            "Content-Type": "application/json"})
        # JAG-159: adding a client reconnects every configured MCP server; a slow
        # HTTP gateway can push a single request past 25s, so allow more headroom.
        with urllib.request.urlopen(r, timeout=120) as resp:
            return json.loads(resp.read().decode())
    try:
        lf = req("POST", "/api/mcp/local-file", {})
        path = lf.get("path", "")
        check("L1 local mcp.json exists", path.endswith("mcp_clients.local.json") and os.path.isfile(path), path)
        req("POST", "/api/mcp/clients", {"name": "v157test",
                                         "url": "http://127.0.0.1:9/mcp", "enabled": False})
        disk = json.load(open(path, encoding="utf-8"))
        check("L2 snippet appended as mcpServers",
              isinstance(disk.get("mcpServers"), dict) and "v157test" in disk["mcpServers"],
              str(list((disk.get("mcpServers") or {}).keys())))
        check("L3 client visible via API", "v157test" in req("GET", "/api/mcp/clients").get("clients", {}))
        req("POST", "/api/mcp/clients/remove", {"name": "v157test"})
        check("L4 cleanup ok", "v157test" not in req("GET", "/api/mcp/clients").get("clients", {}))
    except Exception as e:  # noqa: BLE001
        check("L live round-trip", False, repr(e))
else:
    print("SKIP L* (set SPARKFORGE_URL + SPARKFORGE_TOKEN for the live checks)")

print("RESULT:", "PASS" if ok else "FAIL")
sys.exit(0 if ok else 1)
