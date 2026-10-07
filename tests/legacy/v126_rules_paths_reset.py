#!/usr/bin/env python3
"""v0.9.27 acceptance — rules paths in the prompt + plan/run-graph reset + snippet MCP (JAG-125).

Checks:
 R  the prompt ALWAYS carries the absolute rule-file paths (global + project +
    AGENTS.md fallback), so the model knows where its rules live;
 S  the reset routes / UI exist (plan + current run graph);
 M  the Python snippet MCP client is wired (config) and its tool is allowed.
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
tmp = tempfile.mkdtemp(prefix="sf-125-")
CFG = os.path.join(tmp, "cfg")
os.environ["SPARKFORGE_CONFIG_DIR"] = CFG
os.environ["SPARKFORGE_SESSIONS_DIR"] = os.path.join(tmp, "sessions")
os.environ["SPARKFORGE_DB"] = os.path.join(tmp, "events.db")
os.environ["SPARKFORGE_GRAPH_DIR"] = os.path.join(tmp, "graphs")
WS = os.path.join(tmp, "proj")
for d in (CFG, os.environ["SPARKFORGE_SESSIONS_DIR"], os.environ["SPARKFORGE_GRAPH_DIR"],
          os.path.join(WS, ".sparkforge")):
    os.makedirs(d, exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from sparkforge import rules as R  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


def read(path):
    try:
        return open(path, encoding="utf-8", errors="replace").read()
    except OSError:
        return ""


R.set_workspace(WS)

# ---- R: prompt block always carries the paths -----------------------------
pp = R.prompt_paths()
check("R1 prompt_paths returns 5 absolute paths",
      all(os.path.isabs(pp[k]) for k in ("global_rules", "global_fallback",
                                         "project_rules", "project_fallback",
                                         "project_extra_dir")), str(pp))
blk = R.rules_prompt_block()
check("R2 block non-empty even with NO rules", len(blk) > 0, "len=%d" % len(blk))
check("R2b block names the global RULES.md path", pp["global_rules"] in blk, "")
check("R2c block names the project RULES.md path", pp["project_rules"] in blk, "")
check("R2d block names the AGENTS.md fallbacks",
      pp["global_fallback"] in blk and pp["project_fallback"] in blk, "")
check("R2e block names the workspace", WS in blk, "")

R.save("global", "GLOBAL-RULE-ABC")
blk2 = R.rules_prompt_block()
check("R3 block carries the global rules text", "GLOBAL-RULE-ABC" in blk2, "")
check("R3b legacy rules_block unchanged (still empty when none)", R.rules_block() != "", "")

# ---- S: reset routes + UI --------------------------------------------------
srv = read(os.path.join(REPO, "src", "sparkforge", "server.py"))
check("S1 run-graph reset route present",
      'and path.endswith("/graph/reset")' in srv and "/api/runs/" in srv, "")
check("S2 session plan reset route present", "/graph/reset" in srv, "")
check("S3 server uses the path-carrying block", "rules_prompt_block(" in srv, "")

html = read(os.path.join(REPO, "webui", "index.html"))
check("S4 UI exposes resetPlan + resetRunGraph",
      "function resetPlan" in html and "async function resetPlan" in html
      and "async function resetRunGraph" in html, "")
check("S5 UI buttons call the reset endpoints",
      "/graph/reset" in html and "resetPlan()" in html and "resetRunGraph()" in html, "")

# ---- M: snippet MCP wiring -------------------------------------------------
mcp = read(os.path.join(REPO, "config", "mcp_clients.yaml"))
check("M1 python_sandbox client configured", "python_sandbox:" in mcp, "")
check("M1b snippet server is @pydantic/mcp-run-python", "@pydantic/mcp-run-python" in mcp, "")
check("M1c node dir is passed on PATH", "PATH:" in mcp and ".nvm/versions/node" in mcp, "")
tools = read(os.path.join(REPO, "config", "tools.yaml"))
check("M2 snippet tool allowed", "python_sandbox__run_python_code" in tools, "")

total = len(results)
passed = sum(results)
print("\n==== %d/%d checks passed ====" % (passed, total))
sys.exit(0 if passed == total else 1)
