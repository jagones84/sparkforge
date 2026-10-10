#!/usr/bin/env python3
"""v386 — the `shell` tool honours an explicit working directory (JAG-386).

Reported: the model asked to run a command in a specific repo, but the command
started from the SESSION workspace. Root cause: the `shell` schema advertised
neither `cwd` nor `workspace`, and `_shell` only read an undocumented
`workspace` key — so the `cwd` the model emitted (the name the `git` tool
documents) was silently ignored and the injected session workspace won.

This suite freezes the fix:

  A) the schema now advertises `cwd` (optional; only `command` is required);
  B) an explicit `cwd` reaches the sandbox as its working directory;
  C) `cwd` WINS over the injected `workspace`;
  D) `workspace` alone still works (back-compat);
  E) a missing `cwd` is rejected up front and nothing is executed;
  F) an empty command is still rejected;
  G) approval policy: a `cwd` outside the session workspace escalates to
     `required` (normal mode), inside stays `auto`, `mode=full` disables the gate,
     and a RELATIVE `cwd` resolves against the server process cwd.

Deterministic, no model, no network. `sandbox.run` is stubbed, so no command is
ever really executed.

Run: python3 tests/acceptance/v386_shell_cwd.py
"""
import atexit
import json
import os
import shutil
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
tmp = tempfile.mkdtemp(prefix="sf-386-")
atexit.register(lambda: shutil.rmtree(tmp, ignore_errors=True))
os.environ["SPARKFORGE_CONFIG_DIR"] = os.path.join(tmp, "cfg")
os.environ["SPARKFORGE_SESSIONS_DIR"] = os.path.join(tmp, "sessions")
os.environ["SPARKFORGE_DB"] = os.path.join(tmp, "events.db")
os.environ["SPARKFORGE_GRAPH_DIR"] = os.path.join(tmp, "graphs")
os.environ["SPARKFORGE_EDITS_DIR"] = os.path.join(tmp, "edits")
os.environ["SPARKFORGE_RUNS_DIR"] = os.path.join(tmp, "runs")
for d in ("cfg", "sessions", "graphs", "edits", "runs"):
    os.makedirs(os.path.join(tmp, d), exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from sparkforge import registry, tools  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


def wsdir(name):
    """A workspace under an allowed root (REPO) so it is a realistic session dir."""
    p = os.path.join(REPO, "data", "v386-%s-%d" % (name, os.getpid()))
    os.makedirs(p, exist_ok=True)
    atexit.register(lambda: shutil.rmtree(p, ignore_errors=True))
    return p


# --- stub the sandbox so nothing actually runs -------------------------------
_calls = []


def _fake_run(command, run_id=None, timeout=None, workspace=None, **kw):
    _calls.append({"command": command, "workspace": workspace, "timeout": timeout})
    return {"exit_code": 0, "stdout": "ok", "stderr": "", "backend": "stub",
            "sandboxed": False}


tools.sandbox.run = _fake_run

# --- A: the schema advertises cwd --------------------------------------------
_props = registry.TOOL_SCHEMAS["shell"]["properties"]
check("A1 the shell schema advertises cwd", "cwd" in _props, str(sorted(_props)))
check("A2 only `command` is required (cwd is optional)",
      registry.TOOL_SCHEMAS["shell"]["required"] == ["command"],
      str(registry.TOOL_SCHEMAS["shell"]["required"]))

# --- B: an explicit cwd reaches the sandbox ----------------------------------
b = wsdir("B")
_calls.clear()
rb = tools._shell({"command": "pwd", "cwd": b}, "r1")
check("B1 an explicit absolute cwd reaches the sandbox",
      _calls and _calls[-1]["workspace"] == b, str(_calls))
check("B2 the command still reports success", rb.get("ok") is True, str(rb))

# --- C: cwd WINS over the injected workspace ---------------------------------
c1, c2 = wsdir("C1"), wsdir("C2")
_calls.clear()
tools._shell({"command": "pwd", "cwd": c1, "workspace": c2}, "r2")
check("C1 cwd wins over the workspace key",
      _calls and _calls[-1]["workspace"] == c1, str(_calls))

# --- D: workspace alone is still honoured (back-compat) ----------------------
_calls.clear()
tools._shell({"command": "pwd", "workspace": c2}, "r3")
check("D1 workspace alone still sets the working dir",
      _calls and _calls[-1]["workspace"] == c2, str(_calls))

# --- E: a missing cwd is rejected, nothing runs ------------------------------
_calls.clear()
miss = os.path.join(REPO, "data", "v386-does-not-exist-%d" % os.getpid())
re_ = tools._shell({"command": "pwd", "cwd": miss}, "r4")
check("E1 a missing cwd is rejected with a clear error",
      re_.get("ok") is False and "cwd not found" in (re_.get("error") or ""), str(re_))
check("E2 the sandbox is NOT called for a bad cwd", _calls == [], str(_calls))

# --- F: empty command still rejected -----------------------------------------
check("F1 an empty command is still rejected",
      tools._shell({"command": "   "}, "r5").get("ok") is False)

# --- G: approval policy for an external cwd ----------------------------------
_cfg = json.loads(json.dumps(registry.load_config()))
_cfg.setdefault("approvals", {})
_cfg["approvals"]["mode"] = "normal"
_cfg["approvals"]["outside_workspace"] = "required"
_real_load = registry.load_config
registry.load_config = lambda reload=False: _cfg
try:
    wc = wsdir("G")
    inside = os.path.join(wc, "sub")
    os.makedirs(inside, exist_ok=True)
    outside = os.path.join(REPO, "data", "v386-outside-%d" % os.getpid())
    check("G1 cwd INSIDE the workspace stays auto (read-only command)",
          registry.classify("shell", {"command": "pwd", "cwd": inside},
                            workspace=wc)[0] == "auto",
          str(registry.classify("shell", {"command": "pwd", "cwd": inside}, workspace=wc)))
    check("G2 cwd OUTSIDE the workspace escalates to required",
          registry.classify("shell", {"command": "pwd", "cwd": outside},
                            workspace=wc)[0] == "required",
          str(registry.classify("shell", {"command": "pwd", "cwd": outside}, workspace=wc)))
    check("G3 no cwd -> the normal policy applies (read-only command auto)",
          registry.classify("shell", {"command": "pwd"}, workspace=wc)[0] == "auto",
          str(registry.classify("shell", {"command": "pwd"}, workspace=wc)))
    _cwd0 = os.getcwd()
    os.chdir(wc)
    try:
        check("G4 a RELATIVE cwd resolves against the server process cwd",
              registry.classify("shell", {"command": "pwd", "cwd": "sub"},
                                workspace=wc)[0] == "auto",
              str(registry.classify("shell", {"command": "pwd", "cwd": "sub"}, workspace=wc)))
    finally:
        os.chdir(_cwd0)
    _cfg["approvals"]["mode"] = "full"
    check("G5 approvals.mode=full disables the cwd gate",
          registry.classify("shell", {"command": "pwd", "cwd": outside},
                            workspace=wc)[0] == "auto",
          str(registry.classify("shell", {"command": "pwd", "cwd": outside}, workspace=wc)))
finally:
    registry.load_config = _real_load

print("---")
passed = sum(results)
print("%d/%d PASS" % (passed, len(results)))
sys.exit(0 if passed == len(results) else 1)
