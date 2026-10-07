#!/usr/bin/env python3
"""SparkForge v0.15.6 acceptance — per-session state + command palette (JAG-157).

Checks (exit 0 = pass):
  P*  command palette: scrollable list, keyboard nav, dynamic sessions/skills/MCP
  S*  per-session state: the model lives on the session, plan reloaded on switch
  E*  editor: open by default on the session workspace, per-session tabs
  L*  live: POST /api/sessions/<id>/model round-trips (only if server+token set)
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
ed = read(os.path.join("webui", "assets", "editor.js"))
srv = read("server.py")

# ---- P: command palette ----
check("P1 palette list scrollable", "#palette-results { max-height: 56vh; overflow: auto; }" in html)
check("P2 keyboard nav wired", "function paletteKey" in html and 'addEventListener("keydown", paletteKey)' in html
      and "function paintPalHi" in html)
check("P3 dynamic sessions/skills/mcp", "function loadPaletteDynamic" in html
      and 'api("GET", "/api/skills")' in html and 'api("GET", "/api/mcp/clients")' in html
      and "session \\u25B8" in html)
check("P4 session item switches session", "run: () => selectSession(s)" in html)
check("P5 labels escaped", "esc(i.label)" in html)

# ---- S: per-session state ----
check("S1 selectSession + plan reload", "function selectSession(s)" in html and "loadPlan();" in html)
check("S2 per-session model cache", "_sessModel" in html and "function currentModel()" in html
      and "_sessModel[sessionId]" in html)
check("S3 chooseModel persists to session",
      '/api/sessions/" + encodeURIComponent(sessionId) + "/model"' in html)
check("S4 backend exposes model", '"model": s.get("model")' in srv)
check("S5 backend route POST /model", 'path.endswith("/model")' in srv
      and 'sess["model"] = str(body.get("model")' in srv)
check("S6 backend chat uses session model", srv.count('or sess.get("model")') >= 2)

# ---- E: editor ----
check("E1 per-session tab key", "LS_TABS_S" in ed and "function tabsKey()" in ed)
check("E2 open-by-default flag", "LS_OPEN" in ed and "async function ensureOpen()" in ed)
check("E3 onSessionChange reloads tree", "async function onSessionChange()" in ed and "loadTree();" in ed)
check("E4 exported", "ensureOpen," in ed and "onSessionChange," in ed)
check("E5 index calls it on switch", "SparkEditor.onSessionChange" in html)

# ---- L: live round-trip (optional) ----
base = os.environ.get("SPARKFORGE_URL", "")
tok = os.environ.get("SPARKFORGE_TOKEN", "")
if base and tok:
    def req(method, path, body=None):
        data = json.dumps(body).encode() if body is not None else None
        r = urllib.request.Request(base + path, data=data, method=method,
                                   headers={"Authorization": "Bearer " + tok,
                                            "Content-Type": "application/json"})
        with urllib.request.urlopen(r, timeout=20) as resp:
            return json.loads(resp.read().decode())
    try:
        s = req("GET", "/api/sessions/new?title=v156-tmp")
        sid = s["id"]
        ref = "test:model-x"
        req("POST", "/api/sessions/%s/model" % sid, {"model": ref})
        lst = req("GET", "/api/sessions")
        got = next((x for x in lst.get("sessions", []) if x["id"] == sid), None)
        check("L1 model persists on the session", bool(got) and got.get("model") == ref,
              got and got.get("model"))
        req("DELETE", "/api/sessions/%s" % sid)
    except Exception as e:  # noqa: BLE001
        check("L1 model persists on the session", False, repr(e))
else:
    print("SKIP L1 (set SPARKFORGE_URL + SPARKFORGE_TOKEN for the live check)")

print("RESULT:", "PASS" if ok else "FAIL")
sys.exit(0 if ok else 1)
