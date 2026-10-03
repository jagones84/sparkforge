#!/usr/bin/env python3
"""v0.9.38 acceptance — verifier 'apply-only-if-green' (JAG-131)."""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "src"))
results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


from sparkforge import verify  # noqa: E402
from sparkforge import registry  # noqa: E402

check("V1 defaults off with empty command",
      verify.DEFAULTS["enabled"] is False and verify.DEFAULTS["command"] == "", "")
check("V2 inactive by default (no command)", verify.is_active({}) is False, "")
check("V3 active only when enabled+command",
      verify.is_active({"enabled": True, "command": ""}) is False
      and verify.is_active({"enabled": True, "command": "true"}) is True, "")
check("V4 scope respected",
      verify.should_verify("fs.write", "/a/b.py", {"enabled": True, "command": "x",
                                                   "paths": ["/a"]}) is True
      and verify.should_verify("fs.write", "/z/b.py", {"enabled": True, "command": "x",
                                                       "paths": ["/a"]}) is False
      and verify.should_verify("shell", "/a/b.py", {"enabled": True, "command": "x"}) is False,
      "")
check("V5 registry exposes verifier block", "verifier" in registry.load_config(), "")

_cfg = {"enabled": True, "command": "check", "timeout_secs": 5, "paths": []}

tmp = tempfile.mkdtemp()
path = os.path.join(tmp, "f.py")
with open(path, "w", encoding="utf-8") as f:
    f.write("ORIGINAL\n")

_orig = verify.run_check
try:
    verify.run_check = lambda workspace=None, c=None, run_id=None: (True, "ok")
    res, rep = verify.verify("fs.write", path, {"exists": True, "content": "ORIGINAL\n"},
                             {"ok": True}, c=_cfg)
    with open(path, encoding="utf-8") as f:
        kept = f.read()
    check("V6 green check keeps the edit",
          res.get("ok") is True and rep["green"] is True and kept.strip() == "ORIGINAL", "")

    with open(path, "w", encoding="utf-8") as f:
        f.write("BROKEN\n")
    verify.run_check = lambda workspace=None, c=None, run_id=None: (False, "boom")
    res2, rep2 = verify.verify("fs.write", path, {"exists": True, "content": "ORIGINAL\n"},
                               {"ok": True}, c=_cfg)
    with open(path, encoding="utf-8") as f:
        rolled = f.read()
    check("V7 red check rolls back to the pre-image",
          res2.get("ok") is False and res2.get("verifier_failed") is True
          and rolled.strip() == "ORIGINAL" and rep2.get("rolled_back") is True, "")
finally:
    verify.run_check = _orig

# a NEW file (did not exist before) must be DELETED on red
path2 = os.path.join(tmp, "new.py")
try:
    verify.run_check = lambda workspace=None, c=None, run_id=None: (False, "boom")
    with open(path2, "w", encoding="utf-8") as f:
        f.write("BRAND NEW\n")
    verify.verify("fs.write", path2, {"exists": False, "content": ""},
                  {"ok": True}, c=_cfg)
    check("V8 red check deletes a newly created file", not os.path.exists(path2), "")
finally:
    verify.run_check = _orig

tools_src = open(os.path.join(REPO, "src", "sparkforge", "tools.py"), encoding="utf-8", errors="replace").read()
check("V9 tools wires the verifier for fs.write/fs.edit",
      "_verify_edit(\"fs.write\"" in tools_src and "_verify_edit(\"fs.edit\"" in tools_src, "")

web = open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8", errors="replace").read()
api = open(os.path.join(REPO, "api_v02.py"), encoding="utf-8", errors="replace").read()
cfg_yaml = open(os.path.join(REPO, "config", "tools.yaml"), encoding="utf-8").read()
check("V10 webui verifier card + api + yaml",
      "saveVerifier" in web and "vfCmd" in web
      and '"verifier"' in api and "verifier:" in cfg_yaml, "")

total = len(results)
print("\n==== %d/%d checks passed ====" % (sum(results), total))
sys.exit(0 if all(results) else 1)