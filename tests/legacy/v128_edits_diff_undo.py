#!/usr/bin/env python3
"""v0.9.29 acceptance — file-edit journal: change summary, diff and undo (JAG-127).

 E  the harness journals every fs.write / fs.edit pre-image, keyed by run/session;
 S  the journal yields an IDE-style summary (created N +a · edited M +a −d), a
    side-by-side (before→after) diff and an UNDO that restores the pre-image
    (a created file is removed);
 U  the WebUI exposes it: a change chip in the transcript, a Changes list, a
    left→right diff modal with green adds / red deletions, and undo.
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
tmp = tempfile.mkdtemp(prefix="sf-128-")
os.environ["SPARKFORGE_CONFIG_DIR"] = os.path.join(tmp, "cfg")
os.environ["SPARKFORGE_SESSIONS_DIR"] = os.path.join(tmp, "sessions")
os.environ["SPARKFORGE_DB"] = os.path.join(tmp, "events.db")
os.environ["SPARKFORGE_GRAPH_DIR"] = os.path.join(tmp, "graphs")
os.environ["SPARKFORGE_EDITS_DIR"] = os.path.join(tmp, "edits")
for d in ("cfg", "sessions", "graphs", "edits"):
    os.makedirs(os.path.join(tmp, d), exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from sparkforge import edits  # noqa: E402
from sparkforge import tools  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


def read(path):
    try:
        return open(path, encoding="utf-8", errors="replace").read()
    except OSError:
        return ""


KEY = "sess-128"
mod = os.path.join(tmp, "modified.txt")
new = os.path.join(tmp, "created.txt")

# ---- E: recording ----------------------------------------------------------
r = edits.record(KEY, mod, "a\nb\nc\n", "a\nB\nc\nd\n", "modified")
check("E1 record returns counts", r.get("ok") and r.get("add") == 2 and r.get("del") == 1, str(r))
check("E2 no-op edit is not recorded",
      edits.record(KEY, mod, "same", "same").get("ok") is False, "")
open(mod, "w", encoding="utf-8").write("a\nB\nc\nd\n")          # simulate the write
open(new, "w", encoding="utf-8").write("hello\n")              # created file
edits.record(KEY, new, "", "hello\n", "created")

s = edits.summary(KEY)
check("E3 summary totals", s["totals"]["files"] == 2 and s["totals"]["created"] == 1
      and s["totals"]["modified"] == 1, str(s["totals"]))
check("E4 per-file counts", any(f["path"] == mod and f["add"] == 2 and f["del"] == 1 for f in s["files"]), "")
check("E5 created action flagged", any(f["path"] == new and f["action"] == "created" for f in s["files"]), "")

# ---- S: diff + undo --------------------------------------------------------
d = edits.diff(KEY, mod)
kinds = {row["t"] for row in d["rows"]}
check("S1 diff rows carry before/after", d.get("add") == 2 and d.get("del") == 1, str(d.get("add")))
check("S2 diff has context + change + add rows",
      {"ctx", "chg", "add"} <= kinds, str(sorted(kinds)))
check("S3 diff error for unknown path", edits.diff(KEY, "/nope").get("error") is not None, "")

u = edits.undo(KEY, mod)
check("S4 undo restores the pre-image",
      u.get("ok") and read(mod) == "a\nb\nc\n", repr(read(mod)))
u2 = edits.undo(KEY, new)
check("S5 undo removes a created file",
      u2.get("ok") and not os.path.exists(new), str(u2))
check("S6 journal cleared after undo", edits.summary(KEY)["totals"]["files"] == 0, "")
check("S7 undo with empty journal is a no-op",
      edits.undo(KEY).get("ok") is False, "")

# a fresh create→undo cycle also removes the file
edits.record(KEY, new, "", "x", "created")
open(new, "w", encoding="utf-8").write("x")
edits.undo(KEY)
check("S8 full-session undo removes created file", not os.path.exists(new), "")

# ---- W: harness wiring -----------------------------------------------------
tl = read(os.path.join(REPO, "src", "sparkforge", "tools.py"))
check("W1 tools has the journal hook", "def _journal(" in tl and "edits.record(" in tl, "")
check("W2 fs.write journals", "_journal(run_id, path, before, after" in tl, "")
check("W3 fs.edit journals", "_journal(run_id, path, content, new" in tl, "")
api = read(os.path.join(REPO, "api_v02.py"))
check("W4 api exposes summary/diff/undo", all(x in api for x in
      ("def edits_summary", "def edits_diff", "def edits_undo")), "")
check("W5 api routes wired", all(x in api for x in
      ('"/api/edits"', '"/api/edits/diff"', '"/api/edits/undo"')), "")

# ---- U: WebUI --------------------------------------------------------------
html = read(os.path.join(REPO, "webui", "index.html"))
check("U1 diff modal present", 'id="diffView"' in html and 'id="diffBody"' in html, "")
check("U2 summary chip + undo in transcript", "function editsChip" in html and "function refreshEdits" in html, "")
check("U3 side-by-side diff renderer", "function showDiff" in html and "function closeDiff" in html
      and "function undoDiff" in html, "")
check("U4 green add / red del rows", ".r-add" in html and ".r-del" in html and ".r-chg" in html, "")
check("U5 Changes list in the Files panel",
      'id="editsList"' in html and "async function loadEdits" in html, "")
check("U6 file write/edit card opens the diff",
      "function _toolFilePath" in html and "showDiff(_fp)" in html, "")
check("U7 turn end refreshes the chip", "loadCtx(); refreshEdits();" in html, "")

total = len(results)
passed = sum(results)
print("\n==== %d/%d checks passed ====" % (passed, total))
sys.exit(0 if passed == total else 1)
