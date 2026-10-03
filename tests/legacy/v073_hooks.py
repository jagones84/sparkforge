#!/usr/bin/env python3
"""v0.7.3 acceptance — deterministic lifecycle hooks (JAG-69).

Runs in-process (no server): points SPARKFORGE_HOOKS at a temp config, then
proves that PreToolUse can BLOCK a tool, PostToolUse sees the observation, and
Stop fires at the end of a turn.
"""
import json
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

tmp = tempfile.mkdtemp(prefix="sf-hooks-")
log = os.path.join(tmp, "audit.log")
cfg = os.path.join(tmp, "hooks.yaml")
with open(cfg, "w", encoding="utf-8") as f:
    f.write("hooks:\n")
    f.write('  - event: PreToolUse\n'
            '    matcher: "^shell$"\n'
            '    command: "echo BLOCKED_BY_POLICY >&2; exit 2"\n'
            '    timeout_secs: 10\n')
    f.write('  - event: PostToolUse\n'
            '    matcher: ""\n'
            '    command: "echo $SPARKFORGE_TOOL >> %s"\n'
            '    timeout_secs: 10\n' % log)
    f.write('  - event: Stop\n'
            '    matcher: ""\n'
            '    command: "echo STOP >> %s"\n'
            '    timeout_secs: 10\n' % log)

os.environ["SPARKFORGE_HOOKS"] = cfg
sys.path.insert(0, os.path.join(REPO, "src"))
from sparkforge import hooks  # noqa: E402
from sparkforge import tools  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


loaded = hooks.load(reload=True)
check("H1 config loads the 3 declared hooks", len(loaded) == 3, "n=%d" % len(loaded))

blocked = tools.execute("shell", {"command": "echo SHOULD_NOT_RUN"})
check("H2 PreToolUse exit 2 BLOCKS the tool (never dispatched)",
      blocked.get("hook_blocked") is True
      and "blocked by PreToolUse hook" in (blocked.get("error") or "")
      and "stdout" not in blocked,     # blocked BEFORE dispatch: no execution output
      json.dumps(blocked)[:180])

ok_read = tools.execute("fs.read", {"path": os.path.join(REPO, "README.md"),
                                    "max_bytes": 120})
check("H3 a non-matched tool executes normally", ok_read.get("ok") is True,
      "ok=%s" % ok_read.get("ok"))

hooks.run("Stop", run_id="t")
with open(log, encoding="utf-8") as f:
    lines = f.read().splitlines()
check("H4 PostToolUse + Stop hooks fired (append-only audit log)",
      "fs.read" in lines and "STOP" in lines, "log=%s" % lines)

print("\n==== %d/%d checks passed ====" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
