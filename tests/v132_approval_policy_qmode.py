#!/usr/bin/env python3
"""v0.9.33 acceptance — global approval policy + queue/steer picker (JAG-127c).

 P  the global approval policy (GET /api/tools `policy`, POST /api/tools
    `approvals`) drives classify(): mode=full → never ask; outside_workspace=auto
    → stopping the sandbox-escalation.
 Q  the WebUI: a #qmode picker next to "send" (queue vs steer) and the policy
    card in Config.
"""
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "src"))

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


def read(path):
    try:
        return open(path, encoding="utf-8", errors="replace").read()
    except OSError:
        return ""


from sparkforge import registry  # noqa: E402

_orig_load = registry.load_config
_orig_spec = registry.tool_spec

base = _orig_load()


def _with(**approvals):
    cfg = json.loads(json.dumps(base))
    cfg.setdefault("approvals", {}).update(approvals)
    registry.load_config = lambda reload=False: cfg
    return cfg


try:
    # mode=full → a normally-required tool is auto.
    _with(mode="full")
    d, _r = registry.classify("shell", {"command": "mkdir x && rm -rf build"})
    check("P1 mode=full → required tool becomes auto", d == "auto", str((d, _r)))

    # mode=full still cannot override a hard-deny.
    d2, _r2 = registry.classify("shell", {"command": "rm -rf /"})
    check("P2 mode=full still hard-denies dangerous commands", d2 == "denied", str((d2, _r2)))

    # outside_workspace=auto → no sandbox escalation.
    _with(mode="normal", outside_workspace="auto")
    outside = os.path.join(REPO, "config", "tools.yaml")
    d3, _r3 = registry.classify("fs.read", {"path": outside}, workspace="/tmp/zzz-127c")
    check("P3 outside_workspace=auto → no escalation", d3 == "auto", str((d3, _r3)))

    # default (required) → still escalated.
    _with(mode="normal", outside_workspace="required")
    d4, _r4 = registry.classify("fs.read", {"path": outside}, workspace="/tmp/zzz-127c")
    check("P4 outside_workspace=required → escalated", d4 == "required", str((d4, _r4)))
finally:
    registry.load_config = _orig_load
    registry.tool_spec = _orig_spec

api = read(os.path.join(REPO, "api_v02.py"))
check("P5 GET /api/tools exposes policy", '"policy": registry.load_config().get("approvals")' in api, "")
check("P6 POST /api/tools accepts an approvals dict",
      'isinstance(body.get("approvals"), dict)' in api and '"outside_workspace"' in api, "")

html = read(os.path.join(REPO, "webui", "index.html"))
check("Q1 #qmode picker exists next to send", 'id="qmode"' in html and 'value="steer"' in html
      and 'value="queue"' in html, "")
check("Q2 send honours the picker", 'localStorage.getItem("sf_qmode")' in html, "")
check("Q3 picker persisted + initialised", '_qm.onchange = () => localStorage.setItem("sf_qmode"' in html, "")
check("Q4 policy card in Config", 'data-pol="${k}"' in html
      and 'mk("mode", "full"' in html and 'mk("outside_workspace"' in html, "")
check("Q5 policy card posts to /api/tools", 'approvals: { [b.dataset.pol]: b.dataset.val }' in html, "")

total = len(results)
passed = sum(results)
print("\n==== %d/%d checks passed ====" % (passed, total))
sys.exit(0 if passed == total else 1)
