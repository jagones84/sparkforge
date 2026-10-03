#!/usr/bin/env python3
"""v0.9.25 acceptance — folder picker for a new session (JAG-121)."""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
tmp = tempfile.mkdtemp(prefix="sf-121-")
os.environ["SPARKFORGE_CONFIG_DIR"] = os.path.join(tmp, "cfg")
os.environ["SPARKFORGE_SESSIONS_DIR"] = os.path.join(tmp, "sessions")
os.environ["SPARKFORGE_DB"] = os.path.join(tmp, "events.db")
os.environ["SPARKFORGE_GRAPH_DIR"] = os.path.join(tmp, "graphs")
for k in ("cfg", "sessions", "graphs"):
    os.makedirs(os.path.join(tmp, k), exist_ok=True)
TREE = os.path.join(tmp, "tree")
for d in ("alpha/sub", "beta", ".hidden"):
    os.makedirs(os.path.join(TREE, d), exist_ok=True)
with open(os.path.join(TREE, "file.txt"), "w") as f:
    f.write("x")
os.environ["SPARKFORGE_BROWSE_ROOTS"] = TREE
sys.path.insert(0, os.path.join(REPO, "src"))

from sparkforge import api_v02  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


# ---- F1: listing at the root ----------------------------------------------
d = api_v02.fs_dirs({})
names = [x["name"] for x in d.get("dirs", [])]
check("F1 root listing returns the folder", d.get("path") == os.path.realpath(TREE), str(d.get("path")))
check("F1b only visible directories", names == ["alpha", "beta"], str(names))
check("F1c root has no parent", d.get("parent") is None, str(d.get("parent")))

# ---- F2: navigate into a subfolder ----------------------------------------
d2 = api_v02.fs_dirs({"path": os.path.join(TREE, "alpha")})
check("F2 subfolder lists its children", [x["name"] for x in d2.get("dirs", [])] == ["sub"],
      str(d2.get("dirs")))
check("F2b parent points back to the root", d2.get("parent") == os.path.realpath(TREE), str(d2.get("parent")))

# ---- F3: paths outside the roots are refused ------------------------------
d3 = api_v02.fs_dirs({"path": "/etc"})
check("F3 outside roots refused", bool(d3.get("error")), str(d3.get("error")))

# ---- F4: a non-directory is refused ---------------------------------------
d4 = api_v02.fs_dirs({"path": os.path.join(TREE, "file.txt")})
check("F4 file is not a directory", bool(d4.get("error")), str(d4.get("error")))

# ---- U: WebUI static -------------------------------------------------------
html = open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8").read()
check("U picker markup + browse button + js",
      'id="dirPicker"' in html and "openDirPicker" in html and "async function loadDirs" in html
      and "📁 browse" in html and "/api/fs/dirs" in html, "")

total = len(results)
passed = sum(results)
print("\n==== %d/%d checks passed ====" % (passed, total))
sys.exit(0 if passed == total else 1)
