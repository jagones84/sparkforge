#!/usr/bin/env python3
"""v0.9.28 acceptance — workspace default is not the harness repo + skill viewer (JAG-126).

 R  the default workspace is NOT hardcoded to the harness repo: explicit default
    wins, else the last-used folder, else the user's home;
 S  a session's folder is remembered so the NEXT new session defaults there;
 U  the new-session dialog defaults to the current session's folder, and a skill
    row opens its SKILL.md in a viewer.
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
tmp = tempfile.mkdtemp(prefix="sf-126-")
CFG = os.path.join(tmp, "cfg")
os.environ["SPARKFORGE_CONFIG_DIR"] = CFG
os.environ["SPARKFORGE_SESSIONS_DIR"] = os.path.join(tmp, "sessions")
os.environ["SPARKFORGE_DB"] = os.path.join(tmp, "events.db")
os.environ["SPARKFORGE_GRAPH_DIR"] = os.path.join(tmp, "graphs")
os.environ.pop("SPARKFORGE_WORKSPACE", None)  # make the env override not interfere
A = os.path.join(tmp, "proj-a")
B = os.path.join(tmp, "proj-b")
for d in (CFG, A, B, os.environ["SPARKFORGE_SESSIONS_DIR"], os.environ["SPARKFORGE_GRAPH_DIR"]):
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


HOME = os.path.expanduser("~")

# ---- R: default is not the repo -------------------------------------------
check("R1 cold default is the home, not the repo",
      R.get_workspace() == HOME and R.get_workspace() != REPO,
      "%s (repo=%s)" % (R.get_workspace(), REPO))
R.remember_workspace(A)
check("R2 last-used becomes the default", R.get_workspace() == A, R.get_workspace())
R.set_workspace(B)
check("R3 explicit default wins over last-used", R.get_workspace() == B, R.get_workspace())
check("R3b last-used still recorded", R._read_config().get("last_workspace") == A,
      str(R._read_config().get("last_workspace")))
check("R4 remember refuses a non-existent dir",
      R.remember_workspace("/nope-xyz-126").get("ok") is False, "")

# ---- S: server remembers on session create/load ---------------------------
srv = read(os.path.join(REPO, "src", "sparkforge", "server.py"))
check("S1 server has _remember_workspace", "def _remember_workspace" in srv, "")
check("S1b get_or_create_session remembers", "_remember_workspace(s.get(\"workspace\"))" in srv, "")
api = read(os.path.join(REPO, "api_v02.py"))
check("S2 workspace_set remembers", "remember_workspace(real)" in api, "")

# ---- U: UI ----------------------------------------------------------------
html = read(os.path.join(REPO, "webui", "index.html"))
check("U1 new-session dialog defaults to the current session folder",
      '/api/workspace?session=' in html, "")
check("U2 skill viewer present",
      'id="skillView"' in html and "async function viewSkill" in html
      and "function closeSkillView" in html, "")
check("U2b skill rows are clickable", 'skillrow' in html and "row.onclick = () => viewSkill(" in html, "")
check("U2c Escape closes the viewer", "closeSkillView()" in html, "")

total = len(results)
passed = sum(results)
print("\n==== %d/%d checks passed ====" % (passed, total))
sys.exit(0 if passed == total else 1)
