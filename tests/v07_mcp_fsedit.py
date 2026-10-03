#!/usr/bin/env python3
"""SparkForge v0.7 acceptance — JAG-54: MCP client collegato (pmcp) + fs.edit.

Evidence, not claims. Checks (own instance on SPARKFORGE_TEST_PORT):

  A. config/mcp_clients.yaml exists and the client manager connects to the
     real pmcp server (initialize + tools/list): >0 external tools named
     pmcp__<tool> and they appear in the registry catalog.
  B. POST /api/tools/call {tool: pmcp__gateway.health} executes the REAL
     MCP tool (backend "mcp(pmcp)") with non-empty stdout.
  C. fs.edit (surgical search/replace) through the gate:
     C1 create a file, search absent -> clean error (no partial write)
     C2 ambiguous match (2 hits, replace_all false) -> clean error
     C3 single replacement -> file content updated, replacements=1
     C4 replace_all=true -> every occurrence replaced
  D. agent loop (POST /api/agent/run, live LLM): at least one real MCP tool
     call with backend mcp(pmcp) and a non-empty observation in the trace.

Usage: python3 tests/v07_mcp_fsedit.py
Exit code 0 iff every check passed. Report: data/v07-acceptance.json
"""
import json
import os
import shutil
import sys
import time
import urllib.request

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "src"))

RESULTS = {"task": "JAG-54 v0.7 mcp pmcp + fs.edit", "checks": [], "passed": False}


def check(name, ok, detail=""):
    RESULTS["checks"].append({"name": name, "ok": bool(ok), "detail": str(detail)[:400]})
    print("%s %s %s" % ("PASS" if ok else "FAIL", name, detail))
    return bool(ok)


def skip(name, detail="not configured"):
    """JAG-159: the pmcp gateway is optional — a repo without it must not fail."""
    RESULTS["checks"].append({"name": name, "ok": True, "detail": "SKIP " + detail})
    print("SKIP %s %s" % (name, detail))
    return True


def main():
    ok = True

    # ---- A: client manager connects to the real pmcp server -----------------
    from sparkforge import mcp_client
    from sparkforge import registry
    from sparkforge import tools
    mgr = mcp_client.get_manager()
    mgr.start_all()
    st = mgr.status()
    clients = st.get("clients") or {}
    if not clients:
        skip("A1 pmcp connected", "no MCP client configured")
        skip("A2 tools/list real", "no MCP client configured")
        skip("A3 external tools in registry catalog", "no MCP client configured")
    else:
        if "pmcp" in clients:
            ok &= check("A1 pmcp connected", clients.get("pmcp", {}).get("connected"), clients)
        else:
            skip("A1 pmcp connected", "pmcp not configured")
        ext = mgr.list_external_tools()
        ok &= check("A2 tools/list real", len(ext) > 0, "%d external tools" % len(ext))
        names = [t["name"] for t in registry.catalog() if "__" in t["name"]]
        ok &= check("A3 external tools in registry catalog", len(names) >= len(ext),
                    "catalog=%d external=%d" % (len(names), len(ext)))

    # ---- B: real MCP tools/call through the gate ----------------------------
    # JAG-159: pmcp is optional — skip when it is absent OR the live client
    # reports no tools (a declared-but-empty gateway cannot serve health).
    pmcp_st = clients.get("pmcp") or {}
    if bool(pmcp_st.get("connected")) and int(pmcp_st.get("tools") or 0) > 0:
        res = tools.execute("pmcp__gateway.health", {})
        ok &= check("B1 pmcp__gateway.health executed", res.get("ok"),
                    res.get("stdout", "")[:120])
        ok &= check("B2 backend is mcp(pmcp)", res.get("backend") == "mcp(pmcp)",
                    res.get("backend"))
    else:
        skip("B1 pmcp__gateway.health executed", "pmcp exposes no tools")
        skip("B2 backend is mcp(pmcp)", "pmcp exposes no tools")

    # ---- C: fs.edit ---------------------------------------------------------
    ws = registry.workspace_dir()
    os.makedirs(ws, exist_ok=True)
    p = os.path.join(ws, "v07_fsedit.txt")
    with open(p, "w", encoding="utf-8") as f:
        f.write("alpha\nbeta\nalpha again\n")
    r1 = tools.execute("fs.edit", {"path": p, "search": "missing-text", "replace": "x"})
    ok &= check("C1 search not found -> error", not r1["ok"], r1.get("error"))
    ok &= check("C1b file unchanged", "alpha again" in open(p).read())
    r2 = tools.execute("fs.edit", {"path": p, "search": "alpha", "replace": "X"})
    ok &= check("C2 ambiguous match -> error", not r2["ok"], r2.get("error"))
    r3 = tools.execute("fs.edit", {"path": p, "search": "beta", "replace": "BETA"})
    ok &= check("C3 single replacement", r3["ok"] and r3.get("replacements") == 1, r3)
    ok &= check("C3b content updated", "BETA" in open(p).read())
    r4 = tools.execute("fs.edit", {"path": p, "search": "alpha", "replace": "ALPHA",
                                   "replace_all": True})
    ok &= check("C4 replace_all", r4["ok"] and r4.get("replacements") == 2, r4)
    ok &= check("C4b content updated x2", open(p).read() == "ALPHA\nBETA\nALPHA again\n",
                open(p).read())
    os.remove(p)

    # ---- D: agent loop calls a real MCP tool (own instance, live router) ----
    import subprocess
    import urllib.error
    base = "http://127.0.0.1:%d" % int(os.environ.get("SPARKFORGE_TEST_PORT", 8797))
    env = dict(os.environ)
    env.setdefault("SPARKFORGE_ROUTER", "http://127.0.0.1:8080")
    inst = subprocess.Popen([sys.executable, os.path.join(REPO, "server.py"),
                             "--host", "127.0.0.1", "--port", base.rsplit(":", 1)[1]],
                            cwd=REPO, env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(30):
            try:
                urllib.request.urlopen(base + "/api/tools", timeout=2)
                break
            except Exception:  # noqa: BLE001
                time.sleep(0.5)

        def post(path, body, timeout=180):
            req = urllib.request.Request(base + path, data=json.dumps(body).encode(),
                                         headers={"Content-Type": "application/json"})
            return json.load(urllib.request.urlopen(req, timeout=timeout))

        run = post("/api/agent/run", {"goal": "Call the tool pmcp__gateway.health "
                                      "with empty args, then finish.",
                                      "max_steps": 4})
        mcp_steps = [e for e in run.get("trace", [])
                     if e.get("action") == "tool" and
                     (e.get("tool") or "").startswith("pmcp__")]
        ok &= check("D1 agent loop ran an MCP tool", len(mcp_steps) >= 1,
                    json.dumps(mcp_steps[0])[:200] if mcp_steps else "none")
        if mcp_steps:
            ok &= check("D2 observation non-empty",
                        bool(mcp_steps[0].get("observation")),
                        mcp_steps[0].get("observation", "")[:120])
    except Exception as e:  # noqa: BLE001
        ok &= check("D1 agent loop ran an MCP tool", False, "skipped: %s" % e)
    finally:
        inst.terminate()
        try:
            inst.wait(timeout=5)
        except Exception:  # noqa: BLE001
            inst.kill()

    RESULTS["passed"] = bool(ok)
    out = os.path.join(REPO, "data", "v07-acceptance.json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(RESULTS, f, indent=2)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
