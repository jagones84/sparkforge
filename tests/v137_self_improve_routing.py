#!/usr/bin/env python3
"""v0.9.37 acceptance — routing del self-improvement (JAG-128B)."""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


def read(p):
    try:
        return open(p, encoding="utf-8", errors="replace").read()
    except OSError:
        return ""


import improve  # noqa: E402

check("R1 routing table exposes scopes",
      set(improve.AGENT_WRITE) >= {"memory", "skill", "project", "global", "code"},
      str(sorted(improve.AGENT_WRITE)))
check("R2 memory is auto (free write)", improve.AGENT_WRITE["memory"] == "auto", "")
check("R3 project/global are propose-only",
      improve.AGENT_WRITE["project"] == "propose"
      and improve.AGENT_WRITE["global"] == "propose", "")
check("R4 code is forbidden", improve.AGENT_WRITE["code"] == "forbidden", "")

check("R5 threshold: 5 tool calls triggers",
      improve.should_nudge(used_tools=5) is True, "")
check("R6 threshold: 1 tool call does not trigger",
      improve.should_nudge(used_tools=1) is False, "")
check("R7 threshold: user correction triggers even with 0 tools",
      improve.should_nudge(used_tools=0, corrected=True) is True, "")

rec = improve.propose("project", "usa sempre pytest -q", reason="correzione utente")
check("R8 proposal has id + pending status",
      bool(rec.get("id")) and rec.get("status") == "pending", str(rec))
check("R9 proposal is persisted",
      any(p["id"] == rec["id"] for p in improve.list_proposals()), "")

import rules  # noqa: E402

_rp = rules.prompt_paths()
_rule_files = [_rp["global_rules"], _rp["global_fallback"],
               _rp["project_rules"], _rp["project_fallback"]]


def _snap(paths):
    snap = {}
    for p in paths:
        exists = os.path.exists(p)
        snap[p] = (exists, open(p, encoding="utf-8", errors="replace").read()
                   if exists else "")
    extra = _rp["project_extra_dir"]
    snap[extra] = sorted(os.listdir(extra)) if os.path.isdir(extra) else None
    return snap


_rules_before = _snap(_rule_files)
improve.decide(rec["id"], "deny")
_rules_after = _snap(_rule_files)
check("R10 deny writes no rule file (and status denied)",
      _rules_after == _rules_before
      and improve.get_proposal(rec["id"])["status"] == "denied", "")

check("R11 rules.append exists", hasattr(rules, "append"), "")

import registry  # noqa: E402
sch = registry.TOOL_SCHEMAS.get("improve", {})
check("R12 improve tool declared with propose action",
      "propose" in (sch.get("properties", {}).get("action", {}).get("enum") or []), "")

srv = read(os.path.join(REPO, "server.py"))


def _method_body(src, name):
    i = src.find("def %s(" % name)
    if i < 0:
        return ""
    j = src.find("\n    def ", i + 1)
    return src[i:j if j > 0 else len(src)]


_get_body = _method_body(srv, "do_GET")
_post_body = _method_body(srv, "do_POST")
check("R13 route /api/improve in do_GET and do_POST",
      '"/api/improve"' in _get_body and '"/api/improve"' in _post_body,
      "GET=%s POST=%s" % ('"/api/improve"' in _get_body,
                          '"/api/improve"' in _post_body))
web = read(os.path.join(REPO, "webui", "index.html"))
check("R14 webui listens to improve.proposal",
      'improve.proposal' in web and "function improveCard" in web, "")

import tempfile  # noqa: E402
import shutil  # noqa: E402
import tools  # noqa: E402
import server as server_mod  # noqa: E402

_tmp = tempfile.mkdtemp(prefix="v137-prop-")
_old_dir = improve.PROPOSAL_DIR
_old_publish = server_mod.publish
_captured = []


def _fake_publish(kind, **data):
    _captured.append((kind, data))
    return {"id": len(_captured), "ts": 0.0, "kind": kind, **data}


improve.PROPOSAL_DIR = _tmp
server_mod.publish = _fake_publish
try:
    _res = tools._improve({"action": "propose", "scope": "project",
                           "content": "X", "reason": "r"})
    _pid = (_res.get("proposal") or {}).get("id")
    _props = [d for (k, d) in _captured if k == "improve.proposal"]
    check("R15 improve tool emits improve.proposal",
          len(_props) == 1, str([k for k, _ in _captured]))
    _ev = _props[0] if _props else {}
    check("R16 event carries proposal id + scope",
          bool(_pid) and _ev.get("id") == _pid and _ev.get("scope") == "project",
          "pid=%s ev=%s" % (_pid, _ev))
finally:
    improve.PROPOSAL_DIR = _old_dir
    server_mod.publish = _old_publish
    shutil.rmtree(_tmp, ignore_errors=True)

total = len(results)
print("\n==== %d/%d checks passed ====" % (sum(results), total))
sys.exit(0 if all(results) else 1)
