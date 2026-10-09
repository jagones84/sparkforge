#!/usr/bin/env python3
"""Backfill every org agent's ROLE.md from the local `agency-agents` clone.

The roster was seeded from agency-agents (``scripts/seed_teams.py``) but only the
short LABEL was stored — the agent's role PROMPT (the clone's ``.md`` body) was
never written, so the Bridge prompt and the main-app ``ROLE.md`` were VOID for every
seeded agent. This reads the clone, matches each agent by NAME and writes its body
to ``data/roles/<session>.md`` (the file both UIs show).

NON-DESTRUCTIVE: only an EMPTY role is filled unless ``--force`` is given, so a role
the user has already written is never clobbered.

Usage (on the DGX, from the repo root):
    python3 scripts/seed_agent_roles.py            # fill only EMPTY roles
    python3 scripts/seed_agent_roles.py --force    # overwrite every matched role
Env:
    SPARKFORGE_AGENCY_DIR   the clone (default ~/Repositories/agency-agents)
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "src"))

from sparkforge import agency  # noqa: E402


def main(argv):
    if not agency.available():
        print("agency-agents not found at %s (set SPARKFORGE_AGENCY_DIR)"
              % agency.agency_dir())
        return 2
    force = "--force" in argv[1:]
    res = agency.fill_roles(force=force)
    print("agency: %s" % agency.agency_dir())
    print("filled: %d" % len(res["filled"]))
    print("kept (already set): %d" % len(res["kept"]))
    if res["unmatched"]:
        print("unmatched (%d): %s" % (len(res["unmatched"]),
                                      ", ".join(str(x) for x in res["unmatched"])))
    if res["failed"]:
        print("failed: %s" % ", ".join(str(x) for x in res["failed"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
