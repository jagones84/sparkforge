#!/usr/bin/env python3
"""v0.9.32 acceptance — sandbox-not-gated, inline approval card, think, queue/steer (JAG-127b).

 S  a file op inside the per-run SANDBOX (data/sandbox/<run>) is NOT escalated
    to `required` even when the session folder is elsewhere (the bug where an
    `fs.read` on the agent's own project raised an approval despite `auto`).
 S2 a file op truly OUTSIDE both the session folder and the sandbox IS required.
 T  the model's per-step `thought` is streamed as a `think` delta; the WebUI
    chain-of-thought is expanded by default.
 Q  mid-run queue/steer: /api/chat/steer + push_steer/drain_steer, and the WebUI
    queues messages typed during a running turn (never a second SSE).
 U  approval card uses the real approval id (id_id); scrollbars themed; side
    panels can grow past the old 560px cap.
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "src"))

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


def read(path):
    try:
        return open(path, encoding="utf-8", errors="replace").read()
    except OSError:
        return ""


from sparkforge import registry  # noqa: E402

sandbox_root = registry.workspace_dir()
sbx = os.path.join(sandbox_root, "1234abcd", "proj", "pyproject.toml")
ws = "/home/jagones/Repositories/TESTS/SparkForge_tests"

# JAG-127f: these checks assert the DEFAULT policy — force it, so a user-chosen
# overlay (e.g. mode=full) cannot make them red for the wrong reason.
import json as _json
_real_load = registry.load_config
_cfg = _json.loads(_json.dumps(_real_load()))
_cfg.setdefault("approvals", {})
_cfg["approvals"]["mode"] = "normal"
_cfg["approvals"]["outside_workspace"] = "required"
registry.load_config = lambda reload=False: _cfg
check("S1 sandbox path is NOT escalated (auto respected)",
      registry.classify("fs.read", {"path": sbx}, workspace=ws)[0] == "auto",
      str(registry.classify("fs.read", {"path": sbx}, workspace=ws)))
check("S2 sandbox fs.write is NOT escalated",
      registry.classify("fs.write", {"path": sbx, "content": "x"}, workspace=ws)[0]
      == registry.tool_spec("fs.write")["approval"],
      str(registry.classify("fs.write", {"path": sbx, "content": "x"}, workspace=ws)))
out = os.path.join(REPO, "config", "tools.yaml")
check("S3 a path outside BOTH ws and sandbox is required",
      registry.classify("fs.read", {"path": out}, workspace=ws)[0] == "required",
      str(registry.classify("fs.read", {"path": out}, workspace=ws)))
check("S4 inside the session ws stays auto",
      registry.classify("fs.read", {"path": os.path.join(ws, "README.md")}, workspace=ws)[0] == "auto",
      "")
registry.load_config = _real_load

# ---- steering (source contract; import guarded) ----------------------------
srv = read(os.path.join(REPO, "src", "sparkforge", "server.py"))
check("Q1 /api/chat/steer endpoint exists", 'path == "/api/chat/steer"' in srv, "")
check("Q2 push_steer/drain_steer defined", "def push_steer(" in srv and "def drain_steer(" in srv, "")
check("Q3 steering drained per loop iteration", "for _s in drain_steer(sess[\"id\"]):" in srv, "")
check("Q4 steering published as chat.steer", 'publish("chat.steer"' in srv and 'on_event("chat.steer"' in srv, "")
try:
    sys.path.insert(0, os.path.join(REPO, "src"))
    from sparkforge import server  # noqa: E402
    server.push_steer("v131", "a")
    server.push_steer("v131", "b")
    _got = server.drain_steer("v131")
    check("Q5 inbox round-trip + drain clears", _got == ["a", "b"] and server.drain_steer("v131") == [], str(_got))
except Exception as e:  # noqa: BLE001
    check("Q5 inbox round-trip", False, "import server failed: %s" % e)

# ---- thinking --------------------------------------------------------------
check("T1 per-step thought streamed as think delta",
      '_th = str((act or {}).get("thought")' in srv and 'on_delta("think", _th' in srv, "")

# ---- WebUI -----------------------------------------------------------------
html = read(os.path.join(REPO, "webui", "index.html"))
check("U1 approval card uses the real approval id",
      "const aid = d.id_id || d.id;" in html and "decide(aid," in html, "")
check("U2 think block expanded by default", '<details class="think" open>' in html, "")
check("U3 scrollbars themed", "::-webkit-scrollbar-thumb" in html
      and "scrollbar-color: rgba(139,123,240" in html, "")
check("U4 resizer cap widened past 560", "Math.min(1200, window.innerWidth * 0.72)" in html, "")
check("Q6 queue UI present", 'id="queueBar"' in html and "function enqueueMsg" in html
      and "function flushQueue" in html and "function steerQueued" in html, "")
check("Q7 a running turn queues/steers instead of a 2nd SSE",
      'if (activeSSE) {' in html and 'localStorage.getItem("sf_qmode")' in html, "")
check("Q8 queue flushed on done/error",
      "endStream(); flushQueue();" in html or "linkifyAll(); flushQueue();" in html, "")
check("Q9 chat stream handles approval + steer",
      'es.addEventListener("approval.request", e => { approvalCard(JSON.parse(e.data)); loadApprovals(); });' in html
      and 'es.addEventListener("chat.steer"' in html, "")
check("U5 native controls use a dark color-scheme (no white select popup)",
      "color-scheme: dark;" in html and "#qmode option { background: #121722;" in html, "")

total = len(results)
passed = sum(results)
print("\n==== %d/%d checks passed ====" % (passed, total))
sys.exit(0 if passed == total else 1)
