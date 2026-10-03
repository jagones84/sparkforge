#!/usr/bin/env python3
"""v0.9.16 acceptance — user-managed MCP clients (JAG-108).

The harness must let a USER add/remove external MCP servers (stdio or HTTP)
from the API/UI, persisted in a LOCAL gitignored file so tokens never reach the
tracked repo. The engine lives once in mcp_client.py; clients just call it.
"""
import json
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
tmp = tempfile.mkdtemp(prefix="sf-mcpman-")
os.environ["SPARKFORGE_SESSIONS_DIR"] = os.path.join(tmp, "sessions")
os.environ["SPARKFORGE_DB"] = os.path.join(tmp, "events.db")
os.environ["SPARKFORGE_GRAPH_DIR"] = os.path.join(tmp, "graphs")
os.makedirs(os.environ["SPARKFORGE_SESSIONS_DIR"], exist_ok=True)
os.makedirs(os.environ["SPARKFORGE_GRAPH_DIR"], exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from sparkforge import mcp_client as mc  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


# ---- redirect config to a throwaway directory -----------------------------
base = os.path.join(tmp, "mcp_clients.yaml")
local = os.path.join(tmp, "mcp_clients.local.yaml")
mc.CONFIG_PATH = base
mc.CONFIG_JSON_PATH = os.path.join(tmp, "mcp_clients.json")
mc.CONFIG_LOCAL_PATH = local
mc.CONFIG_LOCAL_JSON_PATH = os.path.join(tmp, "mcp_clients.local.json")

with open(base, "w", encoding="utf-8") as f:
    f.write("env_files:\n  - /tmp/x.env\nclients:\n"
            "  pmcp:\n    url: http://127.0.0.1:3344/mcp\n    enabled: true\n")

# never spawn real processes during the test
_spawned = []
mc.reload = lambda: {"ok": True, "clients": {}}

# ---- merge base + local ----------------------------------------------------
doc = mc.load_doc()
check("base client present", "pmcp" in doc["clients"], str(list(doc["clients"])))
check("base env_files kept", doc["env_files"] == ["/tmp/x.env"], str(doc["env_files"]))

# ---- validation ------------------------------------------------------------
check("reject bad name", "error" in mc.upsert_client("bad name!", {"command": "x"}))
check("reject no transport", "error" in mc.upsert_client("ok1", {"enabled": True}))
check("reject bad args", "error" in mc.upsert_client(
    "ok1", {"command": "x", "args": "notalist"}))

# ---- upsert stdio ----------------------------------------------------------
r = mc.upsert_client("filesystem", {"command": "npx",
                                    "args": ["-y", "@modelcontextprotocol/server-filesystem", "/home"],
                                    "enabled": True})
check("upsert stdio ok", r.get("ok") is True, str(r.get("error", "")))
check("local file written (json)", os.path.isfile(mc.CONFIG_LOCAL_JSON_PATH), mc.CONFIG_LOCAL_JSON_PATH)
check("local file uses mcpServers",
      "mcpServers" in json.dumps(json.load(open(mc.CONFIG_LOCAL_JSON_PATH, encoding="utf-8"))))
doc = mc.load_doc()
check("stdio client merged", doc["clients"].get("filesystem", {}).get("command") == "npx",
      str(doc["clients"].get("filesystem")))

# ---- upsert http with headers (token via env expansion) --------------------
r = mc.upsert_client("github", {"url": "http://127.0.0.1:8791/mcp",
                                "headers": {"Authorization": "Bearer ${GH_TOKEN}"},
                                "enabled": True})
check("upsert http ok", r.get("ok") is True)
doc = mc.load_doc()
check("http transport detected",
      mc.get_manager().status()["clients"]["github"]["transport"] == "http")

# ---- remove a local client -------------------------------------------------
r = mc.remove_client("filesystem")
check("remove local ok", r.get("ok") is True)
check("local client gone", "filesystem" not in mc.load_doc()["clients"])

# ---- remove a base client → local disable override -------------------------
r = mc.remove_client("pmcp")
check("remove base ok", r.get("ok") is True)
st = mc.get_manager().status()
check("base now disabled", st["clients"]["pmcp"]["enabled"] is False,
      str(st["clients"]["pmcp"]))

# ---- test_client never persists and never crashes --------------------------
r = mc.test_client({})
check("test empty spec errors", r.get("ok") is False and "error" in r, str(r))
r = mc.test_client({"command": "definitely-not-a-real-binary-xyz"})
check("test bad command fails cleanly", r.get("ok") is False and "error" in r, str(r))
check("test did not persist", "definitely-not-a-real-binary-xyz" not in
      json.dumps(mc.load_doc()))

total = len(results)
passed = sum(results)
print("%d/%d" % (passed, total))
sys.exit(0 if passed == total else 1)
