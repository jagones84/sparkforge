#!/usr/bin/env python3
"""SparkForge tool registry — declarative tools + allowlist + approval policy.

Loads `config/tools.yaml` (falling back to `config/tools.json`) and answers:
  * which tools exist and are enabled (allowlist)
  * the JSON schema of each tool (for the agent prompt and for MCP tools/list)
  * the approval decision for a concrete action (auto / required / denied / disabled)

Stdlib + PyYAML. No tool is executed here — see tools.py / sandbox.py.
"""

import json
import os
import re
import threading

REPO = os.path.dirname(os.path.abspath(__file__))
CONFIG_YAML = os.path.join(REPO, "config", "tools.yaml")
CONFIG_JSON = os.path.join(REPO, "config", "tools.json")

_lock = threading.RLock()
_cfg = None

# --------------------------------------------------------------- defaults ----

DEFAULT_CONFIG = {
    "version": "0.2",
    "sandbox": {
        "backend": "auto", "image": "alpine:latest", "timeout_secs": 25,
        "network": False, "memory_mb": 256, "pids_limit": 128, "cpus": "1.0",
        "workspace": "data/sandbox",
    },
    "approvals": {"timeout_secs": 300},
    "tools": {},
}

# JSON-schema-ish descriptions exposed to the agent prompt and to MCP clients.
TOOL_SCHEMAS = {
    "shell": {
        "description": ("Run a shell command inside the sandbox (no network, "
                        "read-only rootfs, tmpfs /tmp, scratch /work). Returns "
                        "exit code + captured stdout/stderr."),
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "shell command to execute"},
            "timeout_secs": {"type": "integer", "description": "optional timeout override"},
        },
        "required": ["command"],
        "subject": "command",
    },
    "fs.read": {
        "description": "Read a text file from the harness filesystem (inside allowed roots).",
        "type": "object",
        "properties": {"path": {"type": "string"},
                       "max_bytes": {"type": "integer", "default": 65536}},
        "required": ["path"],
        "subject": "path",
    },
    "fs.write": {
        "description": "Write a text file (inside allowed roots; default: the sandbox workspace).",
        "type": "object",
        "properties": {"path": {"type": "string"}, "content": {"type": "string"},
                       "append": {"type": "boolean", "default": False}},
        "required": ["path", "content"],
        "subject": "path",
    },
    "git": {
        "description": "Run a git subcommand in a repository (read-only ones are auto-approved; push is denied).",
        "type": "object",
        "properties": {"args": {"type": "string", "description": "e.g. 'status --short'"},
                       "cwd": {"type": "string", "description": "optional repo path (default: sparkforge repo)"}},
        "required": ["args"],
        "subject": "args",
    },
    "http": {
        "description": "Fetch a URL (GET) and return status + body head. Host allowlist enforced.",
        "type": "object",
        "properties": {"url": {"type": "string"}, "method": {"type": "string", "default": "GET"},
                       "max_bytes": {"type": "integer", "default": 32768}},
        "required": ["url"],
        "subject": "url",
    },
    "browser": {
        "description": ("Fetch a page and extract readable text (lightweight; not a headless browser). "
                        "Disabled by default."),
        "type": "object",
        "properties": {"url": {"type": "string"}, "max_bytes": {"type": "integer", "default": 32768}},
        "required": ["url"],
        "subject": "url",
    },
    "self": {
        "description": ("Self-knowledge: where the harness is installed (repo, data, "
                        "config paths), how to install a skill/MCP server, and the "
                        "systemd service state. Read-only, always safe."),
        "type": "object",
        "properties": {},
    },
}


# ---------------------------------------------------------------- loading ----

def _load_raw():
    if os.path.exists(CONFIG_YAML):
        try:
            import yaml  # PyYAML
            with open(CONFIG_YAML, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            if isinstance(data, dict):
                return data, "yaml"
        except ImportError:
            raise RuntimeError("PyYAML not installed but config/tools.yaml exists")
        except Exception as e:
            raise RuntimeError("cannot parse config/tools.yaml: %s" % e)
    if os.path.exists(CONFIG_JSON):
        with open(CONFIG_JSON, "r", encoding="utf-8") as f:
            return json.load(f), "json"
    return {}, "defaults"


def load_config(reload=False):
    """Return the merged config (cached). reload=True re-reads from disk."""
    global _cfg
    with _lock:
        if _cfg is not None and not reload:
            return _cfg
        raw, _src = _load_raw()
        cfg = json.loads(json.dumps(DEFAULT_CONFIG))  # deep copy
        for key in ("sandbox", "approvals"):
            if isinstance(raw.get(key), dict):
                cfg[key].update(raw[key])
        cfg["tools"] = raw.get("tools") or {}
        cfg["version"] = raw.get("version", cfg["version"])
        _cfg = cfg
        return _cfg


def save_config(cfg):
    """Persist a partial config overlay back to tools.yaml (keeps it human-editable)."""
    global _cfg
    with _lock:
        try:
            import yaml
            with open(CONFIG_YAML, "w", encoding="utf-8") as f:
                yaml.safe_dump(cfg, f, sort_keys=False, allow_unicode=True,
                               default_flow_style=False)
        except ImportError:
            with open(CONFIG_JSON, "w", encoding="utf-8") as f:
                json.dump(cfg, f, indent=2)
        _cfg = cfg
        return cfg


def workspace_dir():
    return os.path.join(REPO, load_config()["sandbox"]["workspace"])


# ------------------------------------------------------------------ tools ----

def tool_names():
    """All known tools: registry entries from config ∪ shipped schemas."""
    return sorted(set(load_config()["tools"]) | set(TOOL_SCHEMAS))


def tool_spec(name):
    """Merged {name, enabled, approval, ...policy, schema} or None if unknown."""
    schema = TOOL_SCHEMAS.get(name)
    entry = load_config()["tools"].get(name)
    if schema is None and not entry:
        return None
    entry = entry or {}
    return {
        "name": name,
        "enabled": bool(entry.get("enabled", False)),
        "approval": entry.get("approval", "required"),
        "auto_approve": list(entry.get("auto_approve") or []),
        "deny": list(entry.get("deny") or []),
        "allow_hosts": list(entry.get("allow_hosts") or []),
        "roots": list(entry.get("roots") or ["."]),
        "workspace": entry.get("workspace"),
        "schema": schema,
    }


def catalog():
    """Public catalogue for GET /api/tools and MCP tools/list."""
    out = []
    for name in tool_names():
        spec = tool_spec(name)
        out.append({
            "name": name,
            "enabled": spec["enabled"],
            "approval": spec["approval"],
            "auto_approve": spec["auto_approve"],
            "deny": spec["deny"],
            "allow_hosts": spec["allow_hosts"],
            "description": (spec["schema"] or {}).get("description", ""),
            "inputSchema": {k: v for k, v in (spec["schema"] or {}).items()
                            if k in ("type", "properties", "required")},
        })
    return out


def _subject(tool, args):
    """The string a policy regex is matched against for this action."""
    spec = TOOL_SCHEMAS.get(tool) or {}
    key = spec.get("subject")
    if tool == "git":
        return str(args.get("args", ""))
    if key:
        return str(args.get(key, ""))
    return json.dumps(args, sort_keys=True)


def _match(patterns, text):
    for p in patterns:
        try:
            if re.search(p, text):
                return p
        except re.error:
            continue
    return None


def classify(tool, args):
    """Approval decision for a concrete action.

    Returns (decision, reason) with decision in:
      disabled | denied | auto | required
    """
    spec = tool_spec(tool)
    if spec is None:
        return "denied", "unknown tool %r" % tool
    if not spec["enabled"]:
        return "disabled", "tool %r is not in the allowlist (config/tools.yaml)" % tool
    subject = _subject(tool, args)
    hit = _match(spec["deny"], subject)
    if hit:
        return "denied", "matches hard-deny pattern %r" % hit
    if spec["approval"] == "denied":
        return "denied", "tool policy is 'denied'"
    if spec["approval"] == "auto":
        return "auto", "tool policy is 'auto'"
    hit = _match(spec["auto_approve"], subject)
    if hit:
        return "auto", "matches auto-approve pattern %r" % hit
    return "required", "mutating action requires approval"


def resolve_path(path, roots=None):
    """Resolve `path` against the repo and check it stays inside an allowed root."""
    if roots is None:
        roots = ["."]
    base = REPO
    p = path if os.path.isabs(path) else os.path.join(base, path)
    p = os.path.realpath(p)
    for r in roots:
        root = os.path.realpath(r if os.path.isabs(r) else os.path.join(base, r))
        if p == root or p.startswith(root + os.sep):
            return p, None
    return None, "path %r outside allowed roots %s" % (path, roots)
