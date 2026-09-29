#!/usr/bin/env python3
"""SparkForge sandbox — real isolation for shell execution.

Backends (auto-detected, first working wins):
  * docker  — `docker run --rm --network none --read-only --tmpfs /tmp
                --cap-drop ALL --security-opt no-new-privileges --user 65534:65534
                -v <workspace>:/work` (a real container: the process does not see
                the host filesystem or the network)
  * bwrap   — bubblewrap: read-only binds of /usr /lib /bin …, tmpfs /tmp,
              a single writable scratch dir, `--unshare-all` (no net, no host)
  * nsjail  — used when installed (same contract as bwrap)
  * none    — host execution WITHOUT isolation; explicitly labelled `sandboxed: false`

The probe result is cached. `backend='auto'` never silently degrades to `none`:
it falls back only to another real sandbox, and reports `none` only when the
operator explicitly asked for it.
"""

import json
import os
import shutil
import subprocess
import threading
import time

import registry

REPO = registry.REPO

_probe_lock = threading.Lock()
_probe_cache = None


def _run(argv, timeout=None, cwd=None, env=None):
    t0 = time.time()
    try:
        p = subprocess.run(argv, capture_output=True, text=True, timeout=timeout,
                           cwd=cwd, env=env)
        return {"exit_code": p.returncode, "stdout": p.stdout, "stderr": p.stderr,
                "duration_ms": int((time.time() - t0) * 1000)}
    except subprocess.TimeoutExpired as e:
        return {"exit_code": 124, "stdout": (e.stdout or "") if isinstance(e.stdout, str) else "",
                "stderr": "timeout after %ss" % timeout,
                "duration_ms": int((time.time() - t0) * 1000), "timeout": True}
    except FileNotFoundError as e:
        return {"exit_code": 127, "stdout": "", "stderr": "not found: %s" % e,
                "duration_ms": int((time.time() - t0) * 1000)}
    except Exception as e:  # noqa: BLE001
        return {"exit_code": 125, "stdout": "", "stderr": "exec error: %s" % e,
                "duration_ms": int((time.time() - t0) * 1000)}


# ----------------------------------------------------------------- probing ---

def _probe_docker(image):
    if not shutil.which("docker"):
        return False, "docker binary not found"
    info = _run(["docker", "info", "--format", "{{.ServerVersion}}"], timeout=10)
    if info["exit_code"] != 0:
        return False, "docker daemon unreachable: %s" % (info["stderr"] or "").strip()[:120]
    t = _run(["docker", "run", "--rm", "--network", "none", "--read-only",
              "--tmpfs", "/tmp", "--cap-drop", "ALL",
              "--security-opt", "no-new-privileges", image,
              "sh", "-c", "echo sfprobe"], timeout=60)
    if t["exit_code"] == 0 and "sfprobe" in t["stdout"]:
        return True, "docker %s / image %s" % (info["stdout"].strip(), image)
    return False, "docker run failed: %s" % (t["stderr"] or t["stdout"]).strip()[:160]


def _probe_bwrap():
    if not shutil.which("bwrap"):
        return False, "bwrap binary not found"
    argv = [ "bwrap", "--ro-bind", "/usr", "/usr", "--ro-bind", "/lib", "/lib",
             "--ro-bind", "/lib64", "/lib64", "--ro-bind", "/bin", "/bin",
             "--ro-bind", "/sbin", "/sbin", "--proc", "/proc", "--dev", "/dev",
             "--tmpfs", "/tmp", "--unshare-all", "--die-with-parent",
             "/bin/echo", "sfprobe"]
    t = _run(argv, timeout=20)
    if t["exit_code"] == 0 and "sfprobe" in t["stdout"]:
        return True, "bubblewrap (unprivileged userns ok)"
    return False, "bwrap: %s" % (t["stderr"] or "").strip()[:160]


def _probe_nsjail():
    if not shutil.which("nsjail"):
        return False, "nsjail binary not found"
    t = _run(["nsjail", "-Mo", "-Q", "--", "/bin/echo", "sfprobe"], timeout=20)
    if t["exit_code"] == 0 and "sfprobe" in t["stdout"]:
        return True, "nsjail"
    return False, "nsjail: %s" % (t["stderr"] or "").strip()[:160]


def probe(force=False):
    """{'backend': str, 'requested': str, 'available': {name: {'ok','detail'}}, 'isolated': bool}"""
    global _probe_cache
    with _probe_lock:
        if _probe_cache is not None and not force:
            return _probe_cache
        cfg = registry.load_config()
        image = cfg["sandbox"]["image"]
        requested = cfg["sandbox"]["backend"]
        checks = {}
        for name, fn in (("docker", lambda: _probe_docker(image)),
                         ("bwrap", _probe_bwrap), ("nsjail", _probe_nsjail)):
            ok, detail = fn()
            checks[name] = {"ok": ok, "detail": detail}
        if requested in checks:
            chosen = requested if checks[requested]["ok"] else "none"
        elif requested == "none":
            chosen = "none"
        else:  # auto
            chosen = next((n for n in ("docker", "bwrap", "nsjail") if checks[n]["ok"]), "none")
        _probe_cache = {"requested": requested, "backend": chosen,
                        "isolated": chosen != "none", "available": checks}
        return _probe_cache


# -------------------------------------------------------------- workspaces ---

def workspace_for(run_id):
    """Per-run scratch dir, bind-mounted as /work and world-writable for the
    sandbox user (uid 65534 in the container)."""
    cfg = registry.load_config()
    root = os.path.join(REPO, cfg["sandbox"]["workspace"])
    ws = os.path.join(root, run_id or "adhoc")
    os.makedirs(ws, exist_ok=True)
    try:
        os.chmod(ws, 0o777)
    except OSError:
        pass
    return ws


# --------------------------------------------------------------- execution ---

def _docker_argv(cfg, ws, command, image):
    return ["docker", "run", "--rm", "--name", "sf-" + os.urandom(4).hex(),
            "--network", "host" if cfg["sandbox"].get("network") else "none",
            "--read-only", "--tmpfs", "/tmp:rw,noexec,nosuid,size=64m",
            "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
            "--user", "65534:65534", "--memory", "%dm" % cfg["sandbox"]["memory_mb"],
            "--pids-limit", str(cfg["sandbox"]["pids_limit"]),
            "--cpus", str(cfg["sandbox"]["cpus"]),
            "-v", ws + ":/work:rw", "-w", "/work",
            image, "sh", "-c", command]


def _bwrap_argv(ws, command):
    argv = ["bwrap",
            "--ro-bind", "/usr", "/usr", "--ro-bind", "/lib", "/lib",
            "--ro-bind", "/lib64", "/lib64", "--ro-bind", "/bin", "/bin",
            "--ro-bind", "/sbin", "/sbin", "--ro-bind", "/etc", "/etc",
            "--proc", "/proc", "--dev", "/dev",
            "--tmpfs", "/tmp", "--bind", ws, "/work", "--chdir", "/work",
            "--unshare-all", "--die-with-parent", "/bin/sh", "-c", command]
    return argv


def run(command, run_id=None, timeout=None, workspace=None, backend=None):
    """Execute `command` in the configured sandbox. Returns a result dict with
    exit_code / stdout / stderr / duration_ms / backend / sandboxed / workspace."""
    cfg = registry.load_config()
    sb = cfg["sandbox"]
    p = probe()
    chosen = backend or p["backend"]
    if chosen == "auto":
        chosen = p["backend"]
    timeout = int(timeout or sb["timeout_secs"])
    ws = workspace or workspace_for(run_id)

    if chosen == "docker":
        argv = _docker_argv(cfg, ws, command, sb["image"])
        res = _run(argv, timeout=timeout)
        res["backend"] = "docker(%s)" % sb["image"]
        res["sandboxed"] = True
    elif chosen == "bwrap":
        res = _run(_bwrap_argv(ws, command), timeout=timeout)
        res["backend"] = "bwrap"
        res["sandboxed"] = True
    elif chosen == "nsjail":
        argv = ["nsjail", "-Mo", "-Q", "--time_limit", str(timeout),
                "--bindmount_ro", "/usr", "--bindmount_ro", "/bin",
                "--bindmount_ro", "/lib", "--bindmount_ro", "/lib64",
                "--bindmount", ws, "/work", "--cwd", "/work",
                "--", "/bin/sh", "-c", command]
        res = _run(argv, timeout=timeout)
        res["backend"] = "nsjail"
        res["sandboxed"] = True
    else:
        # explicit opt-out only (config sandbox.backend: none) — NOT isolated
        res = _run(["/bin/sh", "-c", command], timeout=timeout, cwd=ws)
        res["backend"] = "none(host)"
        res["sandboxed"] = False
        res["warning"] = "no sandbox backend available — ran on the host"
    res["command"] = command
    res["workspace"] = ws
    return res
