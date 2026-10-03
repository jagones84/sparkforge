"""v169 — every session gets a STABLE human job id JX (JAG-169), exposed by the
API and rendered as JX.TY on the todo nodes. Static + server check.

Run:  python3 tests/v169_job_ids.py
"""
import os
import sys

REPO = "/home/jagones/Repositories/sparkforge"
os.chdir(REPO)
sys.path.insert(0, os.path.join(REPO, "src"))

import py_compile
py_compile.compile(os.path.join(REPO, "src", "sparkforge", "server.py"), doraise=True)

from sparkforge import server

s1 = server.get_or_create_session(None, title="v169-a")
s2 = server.get_or_create_session(None, title="v169-b")
assert s1.get("job") and s2.get("job"), "job not allocated on create"
assert s1["job"] != s2["job"], "two sessions share a job id"
# stability: reloading keeps the SAME job (never shifts)
r = server.get_or_create_session(s1["id"])
assert r["job"] == s1["job"], "job not stable across reload"
# list_sessions exposes it (sidebar badge)
ls = {x["id"]: x for x in server.list_sessions()}
assert ls[s1["id"]].get("job") == s1["job"], "list_sessions missing 'job'"
# history (whole session dict) exposes it
assert (server.load_session(s1["id"]) or {}).get("job") == s1["job"], "history missing 'job'"

# frontend renders JX.TY on the todo nodes (chat + panel)
html = open(os.path.join(REPO, "webui/index.html"), encoding="utf-8").read()
checks = {
    "todo id helper": "function _todoid(node)" in html,
    "chat node shows id": '<span class="tcid"></span>' in html,
    "panel task shows id": '<span class="tcid">${_todoid(n)}</span>' in html,
    "sidebar shows JX": 'class="jid" title="job id (JX)">J${s.job}' in html,
    "graph head shows JX": 'curJob ? ("J" + curJob' in html,
}
bad = [k for k, ok in checks.items() if not ok]
for k, ok in checks.items():
    print(("PASS " if ok else "FAIL ") + k)
assert not bad, "frontend wiring missing: " + ", ".join(bad)

print("v169 OK: jobs", s1["job"], s2["job"], "| RESULT: PASS")
