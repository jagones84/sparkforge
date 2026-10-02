#!/usr/bin/env python3
"""v0.9.30 acceptance — workspace paths, outside-workspace approval, file links (JAG-127).

 W  a Windows path the user copied (Z: = DGX home) resolves to its Linux path, and
    an explicitly-requested folder that does not exist is REJECTED (never silently
    replaced by the default — the bug that made a Z: path look like /home/jagones);
 A  a file read/write/edit OUTSIDE the session workspace is always gated as
    `required`, while the same op inside it keeps the tool's own policy;
 U  the WebUI exposes it: approval policy controls in the Approvals panel and
    readable (non-code) files as clickable links that open in the editor.
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP = os.path.join(REPO, "data", "_v129")
WS = os.path.join(TMP, "ws")
OUT = os.path.join(TMP, "outside")
os.makedirs(WS, exist_ok=True)
os.makedirs(OUT, exist_ok=True)
sys.path.insert(0, REPO)

import rules  # noqa: E402
import registry  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


def read(path):
    try:
        return open(path, encoding="utf-8", errors="replace").read()
    except OSError:
        return ""


HOME = os.path.expanduser("~")

# ---- W: path translation + no silent fallback ------------------------------
check("W1 Z: windows path maps to the home", rules._win_to_posix("Z:\\Repositories\\x") ==
      os.path.join(HOME, "Repositories/x"), rules._win_to_posix("Z:\\Repositories\\x"))
check("W2 forward-slash Z: path maps too", rules._win_to_posix("Z:/a/b") == os.path.join(HOME, "a/b"), "")
check("W3 a plain linux path is untouched", rules._win_to_posix("/tmp/x") == "/tmp/x", "")
check("W4 a real dir validates", rules.check_dir(WS) == os.path.realpath(WS), "")
check("W5 a missing dir is rejected", rules.check_dir("/nope-129-xyz") is None, "")
srv = read(os.path.join(REPO, "server.py"))
check("W6 sessions/new rejects a bad explicit folder",
      "cartella inesistente" in srv and 'ws = qs.get("workspace")' in srv, "")
check("W7 chat passes the workspace to the gate", "_chat_workspace(sess)" in srv, "")

# ---- A: outside-workspace escalation ---------------------------------------
infile = os.path.join(WS, "a.md")
outfile = os.path.join(OUT, "b.md")
check("A1 fs.read INSIDE stays auto",
      registry.classify("fs.read", {"path": infile}, workspace=WS)[0] == "auto",
      str(registry.classify("fs.read", {"path": infile}, workspace=WS)))
check("A2 fs.read OUTSIDE is required",
      registry.classify("fs.read", {"path": outfile}, workspace=WS)[0] == "required",
      str(registry.classify("fs.read", {"path": outfile}, workspace=WS)))
check("A3 fs.write INSIDE keeps its own (non-escalated) policy",
      registry.classify("fs.write", {"path": infile}, workspace=WS)[0]
      == registry.classify("fs.write", {"path": infile})[0],
      str(registry.classify("fs.write", {"path": infile}, workspace=WS)))
check("A3b fs.write OUTSIDE is required regardless of policy",
      registry.classify("fs.write", {"path": outfile}, workspace=WS)[0] == "required",
      str(registry.classify("fs.write", {"path": outfile}, workspace=WS)))
check("A4 no workspace → unchanged auto",
      registry.classify("fs.read", {"path": outfile})[0] == "auto", "")
check("A5 shell is not affected by the workspace rule",
      registry.classify("shell", {"command": "ls"}, workspace=WS)[0] in ("required", "auto"),
      str(registry.classify("shell", {"command": "ls"}, workspace=WS)))
api = read(os.path.join(REPO, "api_v02.py"))
check("A6 gated_call accepts workspace", "def gated_call(tool, args, run_id=None, wait=True, by=\"api\", timeout=None, workspace=None)"
      in api, "")
check("A7 tool_action accepts workspace", "def tool_action(st, tool, args, on_event, workspace=None)" in api, "")

# ---- U: WebUI --------------------------------------------------------------
html = read(os.path.join(REPO, "webui", "index.html"))
check("U1 policy lives in Config only (no Approvals duplicate)",
      'id="configPanel"' in html and 'id="apprPolicy"' not in html, "")
check("U2 no redundant Self/Providers/Keys tabs",
      'data-panel="self"' not in html and 'data-panel="providers"' not in html
      and 'data-panel="keys"' not in html, "")
check("U2b Settings merges self + providers + keys",
      'data-section="settings"' in html and 'id="selfPanel"' in html
      and 'id="provList"' in html and 'id="keysList"' in html, "")
check("U2c session switch refreshes the workspace", "loadCtx(); loadRules(); closeAside();" in html, "")
check("U3 readable files become links", "a.filelink" in html and "function linkifyFiles" in html, "")
check("U4 link opens the file in the editor",
      "function openInEditor" in html and "openInEditor(a.dataset.p)" in html, "")
check("U5 product-file cards get an open button", "tcopen" in html and "openInEditor(_fp)" in html, "")
check("U6 replies are linkified on done", "refreshEdits(); linkifyAll();" in html, "")

try:
    os.rmdir(WS)
    os.rmdir(OUT)
    os.rmdir(TMP)
except OSError:
    pass

total = len(results)
passed = sum(results)
print("\n==== %d/%d checks passed ====" % (passed, total))
sys.exit(0 if passed == total else 1)
