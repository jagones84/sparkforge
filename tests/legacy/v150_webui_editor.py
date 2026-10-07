#!/usr/bin/env python3
"""v0.10 acceptance — WebUI editor dock (JAG-150).

Structural + regression checks for the right-side editor dock: the /assets
static route, the vendored CodeMirror 6 bundle, webui/editor.js, the raw-preview
endpoint, and that the fs engine still round-trips.
"""
import json
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
tmp = tempfile.mkdtemp(prefix="sf-150-")
os.environ["SPARKFORGE_CONFIG_DIR"] = os.path.join(tmp, "cfg")
os.environ["SPARKFORGE_SESSIONS_DIR"] = os.path.join(tmp, "sessions")
os.environ["SPARKFORGE_DB"] = os.path.join(tmp, "events.db")
os.environ["SPARKFORGE_GRAPH_DIR"] = os.path.join(tmp, "graphs")
for k in ("cfg", "sessions", "graphs"):
    os.makedirs(os.path.join(tmp, k), exist_ok=True)

TREE = os.path.join(tmp, "tree")
os.makedirs(TREE, exist_ok=True)
with open(os.path.join(TREE, "note.md"), "w") as f:
    f.write("# Title\n\nhello\n")
os.environ["SPARKFORGE_BROWSE_ROOTS"] = TREE
sys.path.insert(0, os.path.join(REPO, "src"))

from sparkforge import api_v02  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


def read(rel):
    p = os.path.join(REPO, rel)
    if not os.path.exists(p):
        return ""
    with open(p, encoding="utf-8", errors="replace") as f:
        return f.read()


server = read("server.py")
api = read("api_v02.py")
html = read(os.path.join("webui", "index.html"))
editor = read(os.path.join("webui", "assets", "editor.js"))
vendor_dir = os.path.join(REPO, "webui", "assets", "vendor")

# ---- S: server static route -------------------------------------------------
check("S1 /assets route present", 'path.startswith("/assets/")' in server and "_send_asset" in server)
check("S2 asset whitelist + traversal guard",
      "ASSET_EXTS" in server and "startswith(root + os.sep)" in server)

# ---- E: editor module -------------------------------------------------------
check("E1 editor.js exists", len(editor) > 500, "%d bytes" % len(editor))
check("E2 imports the vendored bundle", './vendor/codemirror.js' in editor and "EditorView" in editor)
check("E3 uses the fs endpoints",
      "/api/fs/read" in editor and "/api/fs/write" in editor and "/api/fs/raw" in editor)
check("E4 sanitizes markdown + sandboxes html",
      "DOMPurify" in editor and 'setAttribute("sandbox"' in editor)

# ---- V: vendored libs -------------------------------------------------------
for f in ("codemirror.js", "marked.min.js", "purify.min.js"):
    p = os.path.join(vendor_dir, f)
    sz = os.path.getsize(p) if os.path.exists(p) else 0
    check("V vendored " + f, sz > 1000, "%d bytes" % sz)

# ---- H: index.html wiring ---------------------------------------------------
check("H1 loads the editor module", "/assets/editor.js" in html)
check("H2 loads marked + purify", "/assets/vendor/marked.min.js" in html and "/assets/vendor/purify.min.js" in html)
check("H3 exposes/uses SparkEditor", "SparkEditor" in html)
check("H4 old textarea editor removed", 'id="fileText"' not in html)

# ---- R: raw preview endpoint (images/pdf only) ------------------------------
check("R1 /api/fs/raw route present", '"/api/fs/raw"' in api and "_fs_raw" in api)
check("R2 raw restricted to image/pdf", 'ctype.startswith("image/")' in api)

# ---- X: fs engine still round-trips (regression) ----------------------------
p = os.path.join(TREE, "note.md")
w = api_v02.fs_write({"path": p, "content": "changed\n"})
r = api_v02.fs_read({"path": p})
check("X1 write+read round-trip", w.get("ok") is True and r.get("text") == "changed\n", str(r.get("text")))

report = {"task": "v0.10 webui editor dock", "checks": results, "passed": bool(results) and all(results)}
try:
    os.makedirs(os.path.join(REPO, "data"), exist_ok=True)
    with open(os.path.join(REPO, "data", "v150-webui-editor.json"), "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2)
except OSError:
    pass

total = len(results)
passed = sum(results)
print("\n==== %d/%d checks passed ====" % (passed, total))
sys.exit(0 if passed == total else 1)
