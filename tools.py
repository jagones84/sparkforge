#!/usr/bin/env python3
"""SparkForge tool implementations (shell, fs.read, fs.write, git, http, browser).

Each `execute(tool, args, run_id)` returns a normalised dict:
    {tool, ok, backend, sandboxed, exit_code, stdout, stderr, duration_ms, ...}

Policy (allowlist / approval) is enforced by the caller (server.py) via
registry.classify(); this module only *runs* an already-permitted action.
"""

import ipaddress
import json
import os
import re
import shlex
import time
import urllib.parse
import urllib.request

import registry
import sandbox

REPO = registry.REPO


def _truncate(s, n):
    if not isinstance(s, str):
        s = str(s)
    return s if len(s) <= n else s[:n] + "\n…[truncated %d chars]" % (len(s) - n)


def _host_allowed(url, allow_hosts):
    try:
        host = urllib.parse.urlparse(url).hostname or ""
    except Exception:
        return False, "unparseable url"
    if host in allow_hosts:
        return True, host
    for entry in allow_hosts:
        try:  # support CIDR entries like 10.0.0.0/8
            net = ipaddress.ip_network(entry, strict=False)
            if ipaddress.ip_address(host) in net:
                return True, host
        except ValueError:
            continue
    return False, host


# ------------------------------------------------------------------ shell ----

def _shell(args, run_id):
    command = str(args.get("command", ""))
    if not command.strip():
        return {"ok": False, "error": "empty command"}
    res = sandbox.run(command, run_id=run_id,
                      timeout=args.get("timeout_secs"),
                      workspace=args.get("workspace"))
    res["ok"] = res.get("exit_code") == 0
    return res


# ------------------------------------------------------------------- fs ------

def _fs_read(args, run_id):
    roots = registry.tool_spec("fs.read")["roots"]
    path, err = registry.resolve_path(str(args.get("path", "")), roots)
    if err:
        return {"ok": False, "error": err}
    if not os.path.isfile(path):
        return {"ok": False, "error": "no such file: %s" % path}
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        content = f.read(int(args.get("max_bytes", 65536)))
    return {"ok": True, "path": path, "content": content, "bytes": len(content),
            "backend": "host", "sandboxed": False, "exit_code": 0}


def _fs_write(args, run_id):
    spec = registry.tool_spec("fs.write")
    roots = spec["roots"]
    path, err = registry.resolve_path(str(args.get("path", "")), roots)
    if err:
        return {"ok": False, "error": err}
    os.makedirs(os.path.dirname(path), exist_ok=True)
    content = str(args.get("content", ""))
    mode = "a" if args.get("append") else "w"
    with open(path, mode, encoding="utf-8") as f:
        f.write(content)
    return {"ok": True, "path": path, "bytes": len(content), "append": bool(args.get("append")),
            "backend": "host", "sandboxed": False, "exit_code": 0}


# ------------------------------------------------------------------ git ------

def _git(args, run_id):
    raw = str(args.get("args", "")).strip()
    try:
        argv = shlex.split(raw)
    except ValueError as e:
        return {"ok": False, "error": "bad git args: %s" % e}
    if not argv:
        return {"ok": False, "error": "empty git args"}
    cwd = args.get("cwd") or REPO
    if not os.path.isdir(cwd):
        return {"ok": False, "error": "cwd not found: %s" % cwd}
    t0 = time.time()
    import subprocess
    try:
        p = subprocess.run(["git"] + argv, cwd=cwd, capture_output=True, text=True, timeout=25)
        return {"ok": p.returncode == 0, "exit_code": p.returncode,
                "stdout": p.stdout, "stderr": p.stderr, "cwd": cwd,
                "duration_ms": int((time.time() - t0) * 1000),
                "backend": "host(git)", "sandboxed": False}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": "git failed: %s" % e, "exit_code": 125}


# ----------------------------------------------------------------- http ------

def _http_fetch(url, allow_hosts, max_bytes, method="GET"):
    ok, host = _host_allowed(url, allow_hosts)
    if not ok:
        return None, "host %r not in allow_hosts %s" % (host, allow_hosts)
    req = urllib.request.Request(url, method=method,
                                 headers={"User-Agent": "SparkForge/0.2 (+harness)"})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = resp.read(max_bytes).decode("utf-8", "replace")
            return {"status": resp.status, "body": body, "host": host,
                    "duration_ms": int((time.time() - t0) * 1000)}, None
    except Exception as e:  # noqa: BLE001
        return None, "fetch failed: %s" % e


def _http(args, run_id):
    spec = registry.tool_spec("http")
    data, err = _http_fetch(str(args.get("url", "")), spec["allow_hosts"],
                            int(args.get("max_bytes", 32768)), args.get("method", "GET"))
    if err:
        return {"ok": False, "error": err, "backend": "host(http)", "sandboxed": False}
    body = _truncate(data["body"], 8192)
    return {"ok": True, "exit_code": 0, "stdout": "HTTP %s (%s)\n%s" % (
        data["status"], data["host"], body), "stderr": "",
        "status": data["status"], "bytes": len(data["body"]),
        "duration_ms": data["duration_ms"], "backend": "host(http)", "sandboxed": False}


def _browser(args, run_id):
    spec = registry.tool_spec("browser")
    if not spec["enabled"]:
        return {"ok": False, "error": "browser tool is disabled (set enabled: true in config/tools.yaml)"}
    data, err = _http_fetch(str(args.get("url", "")), spec["allow_hosts"],
                            int(args.get("max_bytes", 32768)))
    if err:
        return {"ok": False, "error": err, "backend": "host(browser)", "sandboxed": False}
    html = data["body"]
    html = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", html)
    text = re.sub(r"(?s)<[^>]+>", " ", html)
    text = re.sub(r"&nbsp;?", " ", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n", text).strip()
    return {"ok": True, "exit_code": 0, "stdout": _truncate(text, 8192), "stderr": "",
            "status": data["status"], "bytes": len(html), "backend": "host(browser)",
            "sandboxed": False, "note": "lightweight HTML->text extractor, not a headless browser"}


def _self(args, run_id):
    """v0.5 self-knowledge: paths, config, docs, systemd state, extension recipe."""
    import subprocess as sp
    info = {
        "ok": True, "backend": "host", "sandboxed": False, "exit_code": 0,
        "name": "SparkForge", "version": "0.5.0",
        "repo_path": REPO,
        "data_dir": os.path.join(REPO, "data"),
        "sessions_dir": os.path.join(REPO, "data", "sessions"),
        "webui": os.path.join(REPO, "webui"),
        "entrypoint": os.path.join(REPO, "server.py"), "port": 8790,
        "router": os.environ.get("SPARKFORGE_ROUTER", "http://127.0.0.1:8080"),
        "config": {"tools": os.path.join(REPO, "config", "tools.yaml"),
                   "routing": os.path.join(REPO, "config", "routing.yaml"),
                   "mcp_clients": os.path.join(REPO, "config", "mcp_clients.yaml")},
        "docs": {"plan": os.path.join(REPO, "docs", "PLAN.md"),
                 "readme": os.path.join(REPO, "README.md"),
                 "architecture": os.path.join(REPO, "docs", "ARCHITECTURE.md")},
        "service": {"unit": "sparkforge.service", "scope": "user",
                    "unit_file": os.path.join(REPO, "deploy", "sparkforge.service"),
                    "restart_cmd": "systemctl --user restart sparkforge.service"},
        "install_skill_mcp": (
            "External MCP servers: add an entry to config/mcp_clients.yaml with "
            "either command+args (stdio) or url (HTTP); tools are discovered via "
            "tools/list and exposed as <client>__<tool> in the registry. Harness-"
            "native tools go in registry.TOOL_SCHEMAS + tools.py with policy in "
            "config/tools.yaml. Apply with POST /api/tools (reload) or "
            "`systemctl --user restart sparkforge.service`."),
    }
    try:
        out = sp.run(["systemctl", "--user", "is-active", "sparkforge.service"],
                     capture_output=True, text=True, timeout=4).stdout.strip()
        info["service"]["active"] = out or "unknown"
    except Exception:
        info["service"]["active"] = "unknown"
    return info


_DISPATCH = {"shell": _shell, "fs.read": _fs_read, "fs.write": _fs_write,
             "git": _git, "http": _http, "browser": _browser, "self": _self}


def execute(tool, args, run_id=None):
    fn = _DISPATCH.get(tool)
    if fn is None:
        return {"ok": False, "error": "no implementation for tool %r" % tool, "tool": tool}
    args = args or {}
    try:
        res = fn(args, run_id)
    except Exception as e:  # noqa: BLE001
        res = {"ok": False, "error": "tool error: %s" % e}
    res["tool"] = tool
    res["args"] = args
    res.setdefault("exit_code", 0 if res.get("ok") else 125)
    return res


def observation(res, max_chars=1600):
    """Render a tool result as the agent's observation line."""
    if not res.get("ok") and res.get("error"):
        return "[%s] ERROR: %s" % (res.get("tool"), res["error"])
    bits = ["[%s] exit=%s backend=%s sandboxed=%s"
            % (res.get("tool"), res.get("exit_code"), res.get("backend"), res.get("sandboxed"))]
    if res.get("stdout"):
        bits.append("stdout: " + _truncate(res["stdout"].strip(), max_chars))
    if res.get("stderr"):
        bits.append("stderr: " + _truncate(res["stderr"].strip(), max_chars))
    if res.get("path"):
        bits.append("path: " + res["path"])
    return "\n".join(bits)
