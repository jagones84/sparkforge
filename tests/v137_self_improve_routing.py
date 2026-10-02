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

total = len(results)
print("\n==== %d/%d checks passed ====" % (sum(results), total))
sys.exit(0 if all(results) else 1)
