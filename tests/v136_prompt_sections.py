#!/usr/bin/env python3
"""v0.9.37 acceptance — architettura prompt a registro (JAG-128A)."""
import os
import sys
import tempfile
from unittest import mock

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


import prompt  # noqa: E402

check("A1 module has render_sections + SECTIONS",
      hasattr(prompt, "render_sections") and hasattr(prompt, "SECTIONS"), "")
ids = [s["id"] for s in prompt.SECTIONS]
check("A2 core sections present",
      {"identity", "tools", "memory", "capability", "prompt-map"}.issubset(set(ids)),
      str(ids))
check("A3 every section kind is static|dynamic",
      all(s.get("kind") in ("static", "dynamic") for s in prompt.SECTIONS), "")

out = prompt.render_sections(None)
check("A4 render non-empty", bool(out.strip()), str(len(out)))
check("A5 identity text present", "SparkForge" in out, "")
check("A6 tool registry block present", "Tool registry" in out, "")

check("B1 rules block injected", "Rules on disk" in out, "")
check("B2 memory policy injected",
      "memory" in out.lower() and "core" in out.lower(), "")
check("B3 dynamic tool_ctx is respected",
      prompt.render_sections(None, tool_ctx="TOOLCTX_SENTINEL").count("TOOLCTX_SENTINEL") == 1, "")

check("C1 manifest declares precedence",
      "PROJECT > GLOBAL > DEFAULT" in out, "")
check("C2 manifest lists section addenda dir",
      "prompt.d" in out, "")
check("C3 capability rule present (no shell for self-questions)",
      "Capability questions" in out and "NEVER run shell" in out, "")

with tempfile.TemporaryDirectory() as tmp:
    with open(os.path.join(tmp, "90-state.md"), "w", encoding="utf-8") as fh:
        fh.write("OVERLAY_ONE")
    with open(os.path.join(tmp, "91-state.md"), "w", encoding="utf-8") as fh:
        fh.write("OVERLAY_TWO")
    with mock.patch.object(prompt, "project_ddir", lambda ws: tmp):
        overlaid = prompt.render_sections(None, ws=tmp)
check("D1 additive overlays for same section concatenate in order",
      "OVERLAY_ONE" in overlaid and "OVERLAY_TWO" in overlaid
      and overlaid.index("OVERLAY_ONE") < overlaid.index("OVERLAY_TWO"), "")

tmp = tempfile.mkdtemp()
os.makedirs(os.path.join(tmp, ".sparkforge", "prompt.d"), exist_ok=True)
with open(os.path.join(tmp, ".sparkforge", "prompt.d", "70-capability.md"),
          "w", encoding="utf-8") as f:
    f.write("PROJECT_OVERLAY_SENTINEL")
out2 = prompt.render_sections(None, ws=tmp)
check("D10 overlay file is appended", "PROJECT_OVERLAY_SENTINEL" in out2, "")
check("D11 default is NOT removed (additive)",
      "Capability questions" in out2, "")

import server  # noqa: E402
sp = server._system_prompt({"id": "sX"})
check("D12 _system_prompt delegates to render_sections",
      "prompt map" in sp and "Tool registry" in sp, "")

import rules  # noqa: E402
wsdir = tempfile.mkdtemp()
os.makedirs(os.path.join(wsdir, ".sparkforge"), exist_ok=True)
with open(os.path.join(wsdir, ".sparkforge", "RULES.md"), "w", encoding="utf-8") as f:
    f.write("RULES_SENTINEL")
with open(os.path.join(wsdir, "AGENTS.md"), "w", encoding="utf-8") as f:
    f.write("AGENTS_SENTINEL")
blk = rules.rules_prompt_block(ws=wsdir)
check("E1 RULES.md read", "RULES_SENTINEL" in blk, "")
check("E2 AGENTS.md is ALSO read (additive, not excluded)", "AGENTS_SENTINEL" in blk, "")

total = len(results)
print("\n==== %d/%d checks passed ====" % (sum(results), total))
sys.exit(0 if all(results) else 1)
