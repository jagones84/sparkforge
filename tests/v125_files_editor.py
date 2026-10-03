#!/usr/bin/env python3
"""v0.9.26 acceptance — workspace file tree + editor (JAG-124).

Unit tests for GET /api/fs/list, GET /api/fs/read, POST /api/fs/write (the
engines `fs_list` / `fs_read` / `fs_write`) plus the WebUI "Files" panel markup,
against a temp tree so nothing outside it can be touched.
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
tmp = tempfile.mkdtemp(prefix="sf-124-")
os.environ["SPARKFORGE_CONFIG_DIR"] = os.path.join(tmp, "cfg")
os.environ["SPARKFORGE_SESSIONS_DIR"] = os.path.join(tmp, "sessions")
os.environ["SPARKFORGE_DB"] = os.path.join(tmp, "events.db")
os.environ["SPARKFORGE_GRAPH_DIR"] = os.path.join(tmp, "graphs")
for k in ("cfg", "sessions", "graphs"):
    os.makedirs(os.path.join(tmp, k), exist_ok=True)

TREE = os.path.join(tmp, "tree")
for d in ("alpha/sub", "beta"):
    os.makedirs(os.path.join(TREE, d), exist_ok=True)
with open(os.path.join(TREE, "notes.md"), "w") as f:
    f.write("hello world\n")
with open(os.path.join(TREE, "file.txt"), "w") as f:
    f.write("x")
with open(os.path.join(TREE, "blob.bin"), "wb") as f:
    f.write(b"\xff\xfe\x00\x01binary")
os.environ["SPARKFORGE_BROWSE_ROOTS"] = TREE
sys.path.insert(0, REPO)

import api_v02  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


# ---- L: list ---------------------------------------------------------------
d = api_v02.fs_list({})
check("L1 root listing returns the tree", d.get("path") == os.path.realpath(TREE), str(d.get("path")))
check("L1b dirs sorted, dotfiles skipped",
      [x["name"] for x in d.get("dirs", [])] == ["alpha", "beta"], str(d.get("dirs")))
check("L1c files listed with size",
      sorted(x["name"] for x in d.get("files", [])) == ["blob.bin", "file.txt", "notes.md"],
      str([x["name"] for x in d.get("files", [])]))

d2 = api_v02.fs_list({"path": os.path.join(TREE, "alpha")})
check("L2 list into a subdir", [x["name"] for x in d2.get("dirs", [])] == ["sub"], str(d2.get("dirs")))

d3 = api_v02.fs_list({"path": os.path.join(TREE, "file.txt")})
check("L3 a file is not a directory", bool(d3.get("error")), str(d3.get("error")))

d4 = api_v02.fs_list({"path": "/etc"})
check("L4 outside roots refused", bool(d4.get("error")), str(d4.get("error")))

# ---- R: read ---------------------------------------------------------------
r = api_v02.fs_read({"path": os.path.join(TREE, "notes.md")})
check("R1 read text file", r.get("text") == "hello world\n" and r.get("binary") is False, str(r.get("text")))

rb = api_v02.fs_read({"path": os.path.join(TREE, "blob.bin")})
check("R2 binary detected, no text", rb.get("binary") is True and rb.get("text") == "", str(rb))

rm = api_v02.fs_read({"path": os.path.join(TREE, "missing.md")})
check("R3 missing file refused", bool(rm.get("error")), str(rm.get("error")))

# ---- W: write (overwrite-only, sandboxed) ----------------------------------
p = os.path.join(TREE, "notes.md")
w = api_v02.fs_write({"path": p, "content": "changed\n"})
check("W1 overwrite existing file", w.get("ok") is True and w.get("bytes") == 8, str(w))
check("W1b content persisted", open(p).read() == "changed\n", repr(open(p).read()))

w2 = api_v02.fs_write({"path": os.path.join(TREE, "brand_new.md"), "content": "x"})
check("W2 refuses to create files", bool(w2.get("error")), str(w2.get("error")))

w3 = api_v02.fs_write({"path": "/etc/passwd", "content": "x"})
check("W3 outside roots refused", bool(w3.get("error")), str(w3.get("error")))

w4 = api_v02.fs_write({"path": p, "content": 123})
check("W4 non-string content refused", bool(w4.get("error")), str(w4.get("error")))

# ---- U: WebUI panel --------------------------------------------------------
html = open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8").read()
check("U rail tab + section + editor wired to the dock",
      'data-panel="files"' in html and 'data-section="files"' in html
      and "function loadFiles" in html and "async function openFile" in html
      and "/api/fs/list" in html and "SparkEditor" in html, "")

total = len(results)
passed = sum(results)
print("\n==== %d/%d checks passed ====" % (passed, total))
sys.exit(0 if passed == total else 1)
