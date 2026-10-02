#!/usr/bin/env python3
"""v0.9.36 acceptance — memoria self-managed: blocco 'core' editabile (JAG-127f).

 C  memory.core_read/core_write round-trip su data/memory/core.md, con cap.
 T  il tool `memory` espone le azioni core/set_core e lo schema le dichiara.
 P  il system prompt inietta il blocco core e la policy spiega quando aggiornarlo.
"""
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


import memory  # noqa: E402

check("C0 core API present", hasattr(memory, "core_read") and hasattr(memory, "core_write")
      and hasattr(memory, "CORE_PATH"), "")
check("C0b path is data/memory/core.md", str(memory.CORE_PATH).endswith(os.path.join("memory", "core.md")),
      str(getattr(memory, "CORE_PATH", "?")))

prev = memory.core_read() if hasattr(memory, "core_read") else ""
try:
    memory.core_write("PROBE-CORE-JAG127F")
    check("C1 round-trip", memory.core_read() == "PROBE-CORE-JAG127F", repr(memory.core_read()))
    memory.core_write("y" * (memory.CORE_MAX + 1000))
    check("C2 capped to CORE_MAX", len(memory.core_read()) == memory.CORE_MAX,
          str(len(memory.core_read())))
finally:
    if prev:
        memory.core_write(prev)
    else:
        try:
            os.remove(memory.CORE_PATH)
        except OSError:
            pass

import registry  # noqa: E402
enum = (registry.TOOL_SCHEMAS.get("memory", {}).get("properties", {})
        .get("action", {}).get("enum") or [])
check("T1 tool schema lists core + set_core", "core" in enum and "set_core" in enum, str(enum))

tools = read(os.path.join(REPO, "tools.py"))
check("T2 tools.py handles core/set_core",
      'action in ("core"' in tools and 'action in ("set_core"' in tools, "")

srv = read(os.path.join(REPO, "server.py"))
prompt_src = read(os.path.join(REPO, "prompt.py"))
check("P1 the prompt injects a Core memory block",
      "Core memory (always visible" in (srv + prompt_src), "")
check("P2 MEMORY_POLICY mentions the core block",
      "set_core" in srv and "CORE (always visible)" in srv, "")
check("P3 the core text is read at prompt build", "core_read()" in (srv + prompt_src), "")

total = len(results)
print("\n==== %d/%d checks passed ====" % (sum(results), total))
sys.exit(0 if all(results) else 1)
