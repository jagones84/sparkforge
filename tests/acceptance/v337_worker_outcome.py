#!/usr/bin/env python3
"""v337 — a subjob outcome is explicit, retried, and never silently returned (JAG-337).

Reported by the user: in the last job run "coder 2" FAILED — it was not retried, the
ball passed to the master with NO trace in either chat, and the failed subjob was
still reported as if it were part of the finished job. Paperclip rule: never sit
silently on blocked work — a worker declares an outcome, is retried, and if it still
cannot finish the handoff is RECORDED in BOTH chats.

This locks the fix:
  * workers end with `STATUS: DONE` / `STATUS: BLOCKED: <why>` / `STATUS: FAILED`;
  * a non-DONE attempt is RETRIED up to SPARKFORGE_JOB_RETRIES extra times;
  * a subjob that still fails is marked `failed` (never `done`) and ESCALATED into
    BOTH the worker's and the coordinator's chat;
  * the coordinator's synthesis message lists the unfinished subjobs;
  * the job record carries `failed_subjobs` and status `partial`.

Deterministic, no model (the agent turn is stubbed).
Run: python3 tests/acceptance/v337_worker_outcome.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-337-")
os.environ["SPARKFORGE_SESSIONS_DIR"] = os.path.join(TMP, "sessions")
os.environ["SPARKFORGE_GRAPH_DIR"] = os.path.join(TMP, "graphs")
os.environ["SPARKFORGE_DB"] = os.path.join(TMP, "events.db")
os.environ["SPARKFORGE_AGENTS_FILE"] = os.path.join(TMP, "agents.json")
os.environ["SPARKFORGE_JOBS_FILE"] = os.path.join(TMP, "jobs.json")
os.environ["SPARKFORGE_JOB_RETRIES"] = "1"
os.makedirs(os.environ["SPARKFORGE_SESSIONS_DIR"], exist_ok=True)
os.makedirs(os.environ["SPARKFORGE_GRAPH_DIR"], exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from sparkforge import server, agents, jobs  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


# ---- A: STATUS parsing (pure) ---------------------------------------------
check("A1 STATUS: DONE -> DONE", jobs.parse_status("did it\nSTATUS: DONE")[0] == "DONE")
check("A2 STATUS: COMPLETE -> DONE", jobs.parse_status("STATUS: COMPLETE")[0] == "DONE")
s, why = jobs.parse_status("STATUS: BLOCKED: no device attached")
check("A3 STATUS: BLOCKED carries the reason", s == "BLOCKED" and "no device" in why, why)
s, why = jobs.parse_status("STATUS: FAILED: gradle no such option")
check("A4 STATUS: FAILED carries the reason", s == "FAILED" and "gradle" in why, why)
check("A5 no STATUS -> None", jobs.parse_status("here is my plan: 1... 2...")[0] is None)
check("A6 case-insensitive + mid-text", jobs.parse_status("blah\nstatus : done")[0] == "DONE")

# ---- B: retry budget ------------------------------------------------------
check("B1 default retry budget = 1 extra attempt", jobs.job_retries() == 1)
os.environ["SPARKFORGE_JOB_RETRIES"] = "0"
check("B2 env can disable retries", jobs.job_retries() == 0)
os.environ["SPARKFORGE_JOB_RETRIES"] = "3"
check("B3 env can raise the budget", jobs.job_retries() == 3)
os.environ["SPARKFORGE_JOB_RETRIES"] = "1"

# ---- C: the delegation demands an explicit outcome ------------------------
MSG = jobs.JobRegistry._delegation_msg(
    "J8", "A8 (Master)", {"id": "J8.2", "deps": ["J8.1"]}, "deploy the app", "- A11: deploy it")
check("C1 the worker is told to end with STATUS: DONE", "STATUS: DONE" in MSG)
check("C2 the worker can declare BLOCKED with a reason", "STATUS: BLOCKED" in MSG)

# ---- D: _one RETRIES then ESCALATES in BOTH chats -------------------------
server.get_or_create_session("sessM", "Master")
server.get_or_create_session("sessW", "Worker")
agents.REGISTRY.designate("sessM", name="Master", role="Head")
agents.REGISTRY.designate("sessW", name="Worker", role="Coder", reports_to="A1")

jid = jobs.JOBS.create("build the app", coordinator="A1", agents=["A1", "A2"])["job"]["id"]
jobs.JOBS._update(jid, lambda j: j.update({"subjobs": {
    jid + ".1": {"id": jid + ".1", "agent": "A2", "status": "running"}}}))

attempts = {"n": 0}


def _always_blocked(sid, message, model=None, jid=None, sender=None, subjob=None):
    attempts["n"] += 1
    return "I could not finish.\nSTATUS: BLOCKED: no device attached"


jobs.JOBS._run_agent = _always_blocked
jobs.JOBS._one(jid, "A2", "sessW", "do it", None, sub_id=jid + ".1", sender="A1 (Master)")

_sub = (jobs.JOBS.get(jid).get("subjobs") or {}).get(jid + ".1") or {}
_run = (jobs.JOBS.get(jid).get("runs") or {}).get("A2") or {}
check("D1 a non-DONE worker is RETRIED (1 + 1 = 2 attempts)", attempts["n"] == 2, str(attempts["n"]))
check("D2 the subjob is marked FAILED, never done", _sub.get("status") == "failed", str(_sub))
check("D3 the run is marked FAILED with the reason",
      _run.get("state") == "failed" and "no device" in (_run.get("error") or ""), str(_run))

winj = server.load_session("sessW").get("injects") or []
cinj = server.load_session("sessM").get("injects") or []
check("D4 the WORKER chat records the return (handoff inject)",
      any(i.get("kind") == "handoff" for i in winj), str(winj[-1:]))
check("D5 the COORDINATOR chat records that it came back",
      any(i.get("kind") == "handoff" and "BACK TO YOU" in (i.get("text") or "") for i in cinj),
      str(cinj[-1:]))

# ---- E: a DONE worker is not retried and succeeds -------------------------
jid2 = jobs.JOBS.create("build the app 2", coordinator="A1", agents=["A1", "A2"])["job"]["id"]
jobs.JOBS._update(jid2, lambda j: j.update({"subjobs": {
    jid2 + ".1": {"id": jid2 + ".1", "agent": "A2", "status": "running"}}}))
done_n = {"n": 0}


def _one_done(sid, message, model=None, jid=None, sender=None, subjob=None):
    done_n["n"] += 1
    return "built it, tests pass.\nSTATUS: DONE"


jobs.JOBS._run_agent = _one_done
jobs.JOBS._one(jid2, "A2", "sessW", "do it", None, sub_id=jid2 + ".1", sender="A1 (Master)")
_sub2 = (jobs.JOBS.get(jid2).get("subjobs") or {}).get(jid2 + ".1") or {}
_run2 = (jobs.JOBS.get(jid2).get("runs") or {}).get("A2") or {}
check("E1 a DONE worker runs exactly once", done_n["n"] == 1, str(done_n["n"]))
check("E2 its subjob is done", _sub2.get("status") == "done", str(_sub2))
check("E3 its run is done", _run2.get("state") == "done", str(_run2))

# ---- F: wiring in the source ---------------------------------------------
jsrc = open(os.path.join(REPO, "src", "sparkforge", "jobs.py"), encoding="utf-8").read()
check("F1 jobs.py parses STATUS", "def parse_status(" in jsrc and "_STATUS_RE" in jsrc)
check("F2 jobs.py retries + escalates", "def _log_escalation(" in jsrc
      and "SPARKFORGE_JOB_RETRIES" in jsrc)
check("F3 the synthesis flags unfinished subjobs", "UNFINISHED SUBJOBS" in jsrc)
check("F4 the job records failed_subjobs / partial",
      "failed_subjobs" in jsrc and '"partial"' in jsrc)

print("---")
ok = sum(1 for r in results if r)
print("%d/%d PASS" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)
