"""Longrun — local agent harness (package).

All runtime modules live in subpackages under `src/longrun/` (core, agent,
orchestrate, plan, tools, model, memory, interop, util, orbit). Filesystem
anchors are centralised in `longrun.util.paths` so a module never depends on
its own location.
"""

