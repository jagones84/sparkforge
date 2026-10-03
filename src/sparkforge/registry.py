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

from .paths import REPO_ROOT as REPO
CONFIG_YAML = os.path.join(REPO, "config", "tools.yaml")
CONFIG_JSON = os.path.join(REPO, "config", "tools.json")
# JAG-82: programmatic policy changes (POST /api/tools, the SETTINGS panel) are
# written to a sparse overlay, never back into the hand-edited tools.yaml.
OVERLAY_YAML = os.path.join(REPO, "data", "tools.overlay.yaml")
OVERLAY_JSON = os.path.join(REPO, "data", "tools.overlay.json")

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
    "runtime": {},
    "verifier": {},
    "bestofn": {},
    "difficulty": {},
    "selfevolve": {},
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
    "fs.edit": {
        "description": ("Surgical file edit: replace a search string with a replacement "
                        "(default: first occurrence; replace_all=true for every "
                        "occurrence). Fails if the search string is not found or is "
                        "ambiguous (multiple matches with replace_all=false)."),
        "type": "object",
        "properties": {"path": {"type": "string"},
                       "search": {"type": "string", "description": "exact text to find"},
                       "replace": {"type": "string", "description": "replacement text"},
                       "replace_all": {"type": "boolean", "default": False}},
        "required": ["path", "search", "replace"],
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
        "description": ("Fetch a URL from the LOCAL allowlist only (default: "
                        "127.0.0.1/localhost). For anything on the public internet "
                        "use the `web` tool instead. Host allowlist enforced."),
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
    "skills": {
        "description": ("Agent skills registry: list available skills (from the "
                        "skills/ tree, one SKILL.md per skill) or read a full "
                        "SKILL.md to follow its instructions/entrypoint."),
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["list", "read"], "default": "list"},
            "name": {"type": "string", "description": "skill name (for action=read)"},
        },
    },
    "memory": {
        "description": ("Your persistent memory across sessions. action=store saves "
                        "a durable fact/preference/decision (optional ttl_secs makes "
                        "it expire; source records provenance); action=recall searches "
                        "past memories; action=recent lists the newest; "
                        "action=invalidate tombstones a wrong/outdated memory (by "
                        "target=id or query) so recall stops surfacing it; "
                        "action=health reports expired/invalidated counts. "
                        "action=core reads / action=set_core rewrites the always-"
                        "visible CORE block. Relevant memories are ALSO auto-injected "
                        "into your prompt each turn, so store things worth "
                        "remembering later."),
        "type": "object",
        "properties": {
            "action": {"type": "string",
                       "enum": ["store", "recall", "recent", "core", "set_core",
                                "invalidate", "health"],
                       "default": "recall"},
            "content": {"type": "string", "description": "text to save (action=store)"},
            "query": {"type": "string", "description": "what to look for (action=recall/invalidate)"},
            "kind": {"type": "string", "description": "optional category filter"},
            "limit": {"type": "integer", "default": 5},
            "source": {"type": "string", "description": "provenance tag (action=store)"},
            "ttl_secs": {"type": "number", "description": "optional lifetime in seconds (action=store)"},
            "target": {"type": "string", "description": "memory id to retire (action=invalidate)"},
            "reason": {"type": "string", "description": "why it's retired (action=invalidate)"},
            "include_invalid": {"type": "boolean", "description": "also return expired/invalidated (action=recall)"},
        },
        "required": [],
        "subject": "action",
    },
    "improve": {
        "type": "object",
        "properties": {
            "action": {"type": "string",
                       "enum": ["propose", "mine", "evolve", "verify", "promote"],
                       "default": "propose"},
            "scope": {"type": "string", "enum": ["skill", "project", "global", "mine"]},
            "content": {"type": "string"},
            "path": {"type": "string",
                     "description": "cartella proposta (per verify/promote)"},
            "reason": {"type": "string"},
        },
        "required": ["action", "scope"],
    },
    "web": {
        "description": ("Public-internet access (JAG-83). action=search runs a web "
                        "search and returns titles/urls/snippets (Tavily or Brave "
                        "when a key is configured, else keyless DuckDuckGo); "
                        "action=fetch downloads a URL and returns readable text "
                        "(via r.jina.ai, else direct HTML->text). Read-only: use it "
                        "for news, docs and facts, then cite the URLs you used."),
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["search", "fetch"], "default": "search"},
            "query": {"type": "string", "description": "search query (action=search)"},
            "url": {"type": "string", "description": "page URL (action=fetch)"},
            "max_results": {"type": "integer", "default": 5},
            "max_bytes": {"type": "integer", "default": 8192},
        },
        "required": [],
        "subject": "query",
    },
    "diff": {
        "description": ("Compare two files or two texts and return a unified diff "
                        "(stdlib difflib). action=files compares two paths (honouring "
                        "the read roots); action=text compares two strings. Read-only."),
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["files", "text"], "default": "files"},
            "a": {"type": "string", "description": "first file path (action=files)"},
            "b": {"type": "string", "description": "second file path (action=files)"},
            "text_a": {"type": "string", "description": "first text (action=text)"},
            "text_b": {"type": "string", "description": "second text (action=text)"},
            "context": {"type": "integer", "default": 3},
        },
        "required": [],
        "subject": "a",
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


def _merge_into(cfg, data):
    """Deep-merge a raw config dict into `cfg` (tools merge per-tool, key by key)."""
    if not isinstance(data, dict):
        return
    for key in ("sandbox", "approvals", "runtime", "verifier", "bestofn",
                "difficulty", "selfevolve"):
        if isinstance(data.get(key), dict):
            cfg[key].update(data[key])
    for tname, tentry in (data.get("tools") or {}).items():
        if isinstance(tentry, dict):
            cur = cfg["tools"].get(tname)
            if isinstance(cur, dict):
                cur.update(tentry)
            else:
                cfg["tools"][tname] = dict(tentry)
        else:
            cfg["tools"][tname] = tentry
    if "version" in data:
        cfg["version"] = data["version"]


def _merged(base_data, overlay_data=None):
    """DEFAULT_CONFIG <- base file <- overlay (later layers win)."""
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))  # deep copy
    _merge_into(cfg, base_data)
    _merge_into(cfg, overlay_data or {})
    return cfg


def load_config(reload=False):
    """Return the merged config (cached). reload=True re-reads from disk."""
    global _cfg
    with _lock:
        if _cfg is not None and not reload:
            return _cfg
        raw, _src = _load_raw()
        cfg = _merged(raw, _load_overlay())
        _cfg = cfg
        return _cfg


_OVERLAY_HEADER = (
    "# SparkForge policy overlay — written automatically by POST /api/tools\n"
    "# (the SETTINGS panel in SparkPulse). Only the keys that DIFFER from\n"
    "# config/tools.yaml live here, so that file stays the hand-edited source\n"
    "# of truth and its comments are never rewritten. Delete this file to fall\n"
    "# back entirely to config/tools.yaml.\n\n"
)


def _load_overlay():
    """The programmatic policy overlay (data/tools.overlay.yaml), or {}."""
    if os.path.exists(OVERLAY_YAML):
        try:
            import yaml
            with open(OVERLAY_YAML, "r", encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        except Exception:
            return {}
    if os.path.exists(OVERLAY_JSON):
        try:
            with open(OVERLAY_JSON, "r", encoding="utf-8") as f:
                return json.load(f) or {}
        except Exception:
            return {}
    return {}


def _diff_overlay(cfg, base_data):
    """Only the keys in `cfg` that differ from the base file's own state."""
    eff = _merged(base_data)  # what the config would be WITHOUT any overlay
    out = {}
    tools_diff = {}
    eff_tools = eff.get("tools") or {}
    for tname, tentry in (cfg.get("tools") or {}).items():
        if not isinstance(tentry, dict):
            continue
        e = eff_tools.get(tname) or {}
        if not isinstance(e, dict):
            e = {}
        d = {k: v for k, v in tentry.items() if e.get(k) != v}
        if d:
            tools_diff[tname] = d
    if tools_diff:
        out["tools"] = tools_diff
    for key in ("sandbox", "approvals", "runtime", "verifier", "bestofn",
                "difficulty", "selfevolve"):
        e = eff.get(key) or {}
        d = {k: v for k, v in (cfg.get(key) or {}).items() if e.get(k) != v}
        if d:
            out[key] = d
    return out


def _write_overlay(overlay):
    """Atomically write the sparse overlay (never touches config/tools.yaml)."""
    os.makedirs(os.path.dirname(OVERLAY_YAML), exist_ok=True)
    try:
        import yaml
        tmp = OVERLAY_YAML + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(_OVERLAY_HEADER)
            if overlay:
                yaml.safe_dump(overlay, f, sort_keys=False, allow_unicode=True,
                               default_flow_style=False)
            else:
                f.write("{}\n")
        os.replace(tmp, OVERLAY_YAML)
    except ImportError:
        with open(OVERLAY_JSON, "w", encoding="utf-8") as f:
            json.dump(overlay, f, indent=2)


def save_config(cfg):
    """Persist ONLY the delta vs config/tools.yaml into data/tools.overlay.yaml.

    JAG-82: the SETTINGS panel flips approval policy per tool. Rewriting
    config/tools.yaml mixed the app's changes with the hand-edited file and
    destroyed its documentation. Now that file is never touched: we diff the
    live config against it and store only the changed keys in a gitignored
    overlay that load_config() merges on top. Delete the overlay to revert.
    """
    global _cfg
    with _lock:
        base, _src = _load_raw()
        _write_overlay(_diff_overlay(cfg, base))
        _cfg = cfg
        return cfg


def workspace_dir():
    return os.path.join(REPO, load_config()["sandbox"]["workspace"])


# ------------------------------------------------------------------ tools ----

def _external_tools():
    """External MCP tools (mcp_client), lazily; empty on any failure."""
    try:
        from . import mcp_client
        if not mcp_client.get_manager().sessions:
            mcp_client.get_manager().start_all()
        return {t["name"]: t for t in mcp_client.list_tools()}
    except Exception:
        return {}


def tool_names():
    """All known tools: registry entries from config ∪ shipped schemas ∪ external MCP."""
    return sorted(set(load_config()["tools"]) | set(TOOL_SCHEMAS) | set(_external_tools()))


def tool_spec(name):
    """Merged {name, enabled, approval, ...policy, schema} or None if unknown."""
    schema = TOOL_SCHEMAS.get(name)
    ext = None
    if schema is None:
        ext = _external_tools().get(name)
        if ext:
            ins = ext.get("inputSchema") or {}
            schema = {"description": ext.get("description", ""),
                      "type": ins.get("type", "object"),
                      "properties": ins.get("properties", {}),
                      "required": ins.get("required", [])}
    entry = load_config()["tools"].get(name)
    if schema is None and not entry:
        return None
    if entry is None and ext:
        entry = {}  # external MCP default policy below
    entry = entry or {}
    return {
        "name": name,
        # JAG-80: external MCP tools (the pmcp gateway) are OPT-IN. Shipping 26
        # gateway tools (23 of them approval-gated) into the chat prompt made the
        # model call `pmcp__gateway.request_capability` instead of its own
        # tools/skills — and that call froze the turn on the approval gate. Only
        # tools explicitly enabled in config/tools.yaml are offered.
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


_ENV_ASSIGN_RE = re.compile(
    r"^\s*(?:[A-Za-z_][A-Za-z0-9_]*=(?:'[^']*'|\"[^\"]*\"|\S*)\s+)+")


def _subject(tool, args):
    """The string a policy regex is matched against for this action."""
    spec = TOOL_SCHEMAS.get(tool) or {}
    key = spec.get("subject")
    if tool == "git":
        return str(args.get("args", ""))
    if tool == "shell":
        # JAG-85: `TZ=Europe/Rome date '…'` is still a read-only `date`. Drop the
        # leading `VAR=value` assignments so the auto-approve patterns (and the
        # hard-deny list) match the REAL command. A pointless approval gate here
        # cost a 30s wait and made a simple "what day is it" turn look stuck.
        return _ENV_ASSIGN_RE.sub("", str(args.get("command", "")))
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


def _under(path, root):
    """True when `path` is inside `root` (both realpath'd)."""
    try:
        p = os.path.realpath(path)
        r = os.path.realpath(root)
        return p == r or p.startswith(r + os.sep)
    except Exception:  # noqa: BLE001
        return False


def classify(tool, args, workspace=None):
    """Approval decision for a concrete action.

    JAG-127: when a `workspace` is given, a file op (fs.read/write/edit) targeting
    a path OUTSIDE it is always `required` — reading or writing outside the folder
    the user opened must be confirmed, even if the tool policy is 'auto'.
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
    # JAG-127c: global approval switch, set from the Config panel (persisted in
    # the overlay). `full` = never ask for anything (hard-deny/disabled still
    # win); `outside_workspace` = required|auto controls the sandbox-escalation.
    ap = load_config().get("approvals") or {}
    if str(ap.get("mode", "normal")).lower() in ("full", "auto", "yolo"):
        return "auto", "approvals.mode=full — never ask"
    if workspace and tool in ("fs.read", "fs.write", "fs.edit") \
            and str(ap.get("outside_workspace", "required")).lower() == "required":
        p, _err = resolve_path(str((args or {}).get("path", "")), spec["roots"],
                               base=workspace)
        # JAG-127b: the per-run sandbox (data/sandbox/<run>) is the agent's own
        # scratch area — it is always "inside" even when the session folder is
        # elsewhere. Without this every sandbox file op was escalated to
        # `required`, so a `fs.read` on the agent's OWN project raised an
        # approval the user never asked for (policy `auto` ignored).
        if p and not _under(p, workspace) and not _under(p, workspace_dir()):
            return "required", "path outside the session workspace"
    if spec["approval"] == "auto":
        return "auto", "tool policy is 'auto'"
    hit = _match(spec["auto_approve"], subject)
    if hit:
        return "auto", "matches auto-approve pattern %r" % hit
    return "required", "mutating action requires approval"


def resolve_path(path, roots=None, base=None):
    """Resolve `path` against a base dir (default: the repo) + check allowed roots.

    JAG-191: when a session workspace is open, a RELATIVE path resolves against
    it — not the harness repo — so `fs.write {"path": "foo.txt"}` lands in the
    folder the user actually opened (mirrors the shell tool, which already uses
    the workspace as cwd). Absolute paths are untouched; the roots stay
    repo-relative so the allow-list semantics do not change.
    """
    if roots is None:
        roots = ["."]
    # JAG-207 (v207): a null byte makes os.path.realpath raise ValueError
    # ("embedded null byte"); reject it gracefully instead of crashing a tool.
    if "\x00" in str(path):
        return None, "path contains a null byte"
    base = os.path.realpath(base) if base else REPO
    p = path if os.path.isabs(path) else os.path.join(base, path)
    p = os.path.realpath(p)
    for r in roots:
        root = os.path.realpath(r if os.path.isabs(r) else os.path.join(REPO, r))
        if p == root or p.startswith(root + os.sep):
            return p, None
    return None, "path %r outside allowed roots %s" % (path, roots)
