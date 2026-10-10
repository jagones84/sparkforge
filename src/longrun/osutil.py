#!/usr/bin/env python3
"""Longrun OS abstraction — the single place for platform-specific bits.

The harness was written for POSIX (the DGX). Only a handful of operations are
actually platform-dependent; they live here so the rest of the code stays clean:

  * shell_argv     — ['/bin/sh','-c',cmd] on POSIX, ['cmd','/c',cmd] on Windows
  * popen_kwargs   — put the child in its own process group, so it can be killed
                     as a tree (start_new_session on POSIX, CREATE_NEW_PROCESS_GROUP
                     on Windows)
  * kill_tree      — SIGTERM->SIGKILL the group (POSIX) / taskkill /T /F (Windows)
  * resolve_script — npx/pip -> npx.cmd/pip.exe on Windows (PATHEXT resolution)

Every function accepts ``on_windows=None`` (default = the real platform) so the
Windows branch is unit-testable from Linux.
"""

import os
import shutil
import signal
import subprocess

IS_WINDOWS = os.name == "nt"
IS_POSIX = os.name == "posix"

# subprocess.CREATE_NEW_PROCESS_GROUP only exists on Windows; keep a literal
# fallback so the Windows branch is importable (and testable) everywhere.
_CREATE_NEW_PROCESS_GROUP = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)


def _win(on_windows=None):
    """True when targeting Windows (explicit flag wins over the real platform)."""
    return IS_WINDOWS if on_windows is None else bool(on_windows)


def shell_argv(command, on_windows=None):
    """An argv that runs ``command`` through the system shell."""
    if _win(on_windows):
        comspec = os.environ.get("COMSPEC") or "cmd.exe"
        return [comspec, "/c", command]
    return ["/bin/sh", "-c", command]


def popen_kwargs(on_windows=None):
    """Popen kwargs that isolate the child so the whole tree can be killed."""
    if _win(on_windows):
        return {"creationflags": _CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session": True}


def kill_tree(proc, on_windows=None, grace=5):
    """Terminate ``proc`` AND its children. Best effort, never raises."""
    if proc is None:
        return
    if _win(on_windows):
        try:
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                           capture_output=True, text=True, timeout=10)
        except Exception:  # noqa: BLE001
            try:
                proc.kill()
            except Exception:  # noqa: BLE001
                pass
        return
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
    except Exception:  # noqa: BLE001
        try:
            proc.terminate()
        except Exception:  # noqa: BLE001
            pass
    try:
        proc.wait(timeout=grace)
    except Exception:  # noqa: BLE001
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except Exception:  # noqa: BLE001
            try:
                proc.kill()
            except Exception:  # noqa: BLE001
                pass


def service_hint():
    """How to (re)start the harness on this platform — informational only."""
    if IS_WINDOWS:
        return "run.ps1 (or `python server.py`); install as a service with nssm"
    if IS_POSIX:
        return "systemctl --user restart longrun.service"
    return "restart the server process"


def resolve_script(name, on_windows=None):
    """Resolve a command name to something spawnable (npx -> npx.cmd on Windows)."""
    if not name or not _win(on_windows):
        return name
    if os.path.isabs(name) or ("/" in name) or ("\\" in name):
        return name
    found = shutil.which(name)
    if found:
        return found
    for ext in (".cmd", ".exe", ".bat"):
        found = shutil.which(name + ext)
        if found:
            return found
    return name
