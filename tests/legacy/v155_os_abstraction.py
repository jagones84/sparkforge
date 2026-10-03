#!/usr/bin/env python3
"""SparkForge v0.15.5 acceptance — OS abstraction for the Windows-native port.

The core is becoming OS-agnostic (native Python on Linux *and* Windows). All
platform-specific bits live in `osutil.py`; this test pins that contract and
proves every POSIX-only call site routes through it (so Linux stays unchanged).

Checks (exit 0 = pass):
  O*-unit   osutil behaviour on both platforms (Windows branch flagged on Linux)
  O*-exec   a real command really runs through osutil.shell_argv here
  O*-site   hooks.py / mcp_client.py / sandbox.py / server.py / tools.py use it
"""
import os
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "src"))

from sparkforge import osutil  # noqa: E402

ok = True


def check(name, cond, detail=""):
    global ok
    ok &= bool(cond)
    print(("PASS " if cond else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


def read(rel):
    p = os.path.join(REPO, rel)
    q = os.path.join(REPO, "src", "sparkforge", rel)
    if not os.path.dirname(rel) and os.path.isfile(q):
        p = q
    elif not os.path.isfile(p) and os.path.isfile(q):
        p = q
    return open(p, encoding="utf-8").read()


# ---- unit: the two branches are deterministic on any host -----------------
check("O1 shell_argv POSIX", osutil.shell_argv("echo hi", on_windows=False) == ["/bin/sh", "-c", "echo hi"],
      osutil.shell_argv("echo hi", on_windows=False))
win_argv = osutil.shell_argv("echo hi", on_windows=True)
check("O2 shell_argv Windows", win_argv[1:] == ["/c", "echo hi"] and win_argv[0].lower().endswith("cmd.exe"),
      win_argv)

check("O3 popen_kwargs POSIX", osutil.popen_kwargs(on_windows=False) == {"start_new_session": True},
      osutil.popen_kwargs(on_windows=False))
win_kw = osutil.popen_kwargs(on_windows=True)
check("O4 popen_kwargs Windows", "creationflags" in win_kw and len(win_kw) == 1, win_kw)

check("O5 resolve_script passthrough POSIX", osutil.resolve_script("npx", on_windows=False) == "npx")
check("O6 resolve_script abs path Windows",
      osutil.resolve_script(r"C:\tools\npx.cmd", on_windows=True) == r"C:\tools\npx.cmd" and
      osutil.resolve_script("npx", on_windows=True) != "")  # never returns empty

check("O7 service_hint is a non-empty string",
      isinstance(osutil.service_hint(), str) and len(osutil.service_hint()) > 0, osutil.service_hint())

check("O8 IS_* flags", isinstance(osutil.IS_WINDOWS, bool) and isinstance(osutil.IS_POSIX, bool)
      and (osutil.IS_WINDOWS != osutil.IS_POSIX), (osutil.IS_WINDOWS, osutil.IS_POSIX))


# ---- exec: shell_argv + popen_kwargs + kill_tree really work here ---------
p = subprocess.run(osutil.shell_argv("echo osutil-ok"), capture_output=True, text=True, timeout=20)
check("O9 exec via shell_argv", p.returncode == 0 and "osutil-ok" in p.stdout, (p.returncode, p.stdout.strip()))

proc = subprocess.Popen(osutil.shell_argv("echo done"), stdout=subprocess.PIPE, text=True,
                        **osutil.popen_kwargs())
proc.wait()
osutil.kill_tree(proc)          # must be a no-op, never raise, on an exited proc
osutil.kill_tree(None)          # must never raise
check("O10 kill_tree is safe", True)

check("O11 kill_tree targets the tree",
      "taskkill" in read("osutil.py") and "killpg" in read("osutil.py"))


# ---- call sites: no POSIX assumptions left outside osutil -----------------
hooks_src = read("hooks.py")
check("O12 hooks.py uses shell_argv", "osutil.shell_argv(" in hooks_src and '"/bin/sh"' not in hooks_src)

mcp_src = read(os.path.join("mcp_client.py"))
check("O13 mcp_client.py spawns through osutil",
      "osutil.resolve_script(" in mcp_src and "osutil.popen_kwargs(" in mcp_src
      and "osutil.kill_tree(" in mcp_src)

sb_src = read(os.path.join("sandbox.py"))
check("O14 sandbox.py host path through osutil",
      "osutil.shell_argv(" in sb_src and "osutil.popen_kwargs(" in sb_src and "osutil.kill_tree(" in sb_src)

srv_src = read(os.path.join("server.py"))
tools_src = read(os.path.join("tools.py"))
check("O15 server.py systemctl guarded",
      "osutil.service_hint()" in srv_src and "osutil.IS_POSIX" in srv_src
      and '"restart_cmd": "systemctl' not in srv_src)
check("O16 tools.py systemctl guarded",
      "osutil.service_hint()" in tools_src and "osutil.IS_POSIX" in tools_src
      and '"restart_cmd": "systemctl' not in tools_src)

check("O17 Windows launcher present", os.path.isfile(os.path.join(REPO, "run.ps1")))

print("RESULT:", "PASS" if ok else "FAIL")
sys.exit(0 if ok else 1)
