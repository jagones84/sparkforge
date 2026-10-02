#!/usr/bin/env python3
"""SparkForge rules — global (user) + project (workspace) instructions (JAG-114).

Mirrors the AGENTS.md convention: instructions are discovered at two scopes and
concatenated broadest -> most specific (project wins), then injected into the
system prompt of both chat and the agent loop.

  * GLOBAL (user, all sessions):  ~/.config/sparkforge/RULES.md
                                  (fallback: ~/.config/sparkforge/AGENTS.md)
  * PROJECT (the selected workspace): <ws>/.sparkforge/RULES.md + <ws>/.sparkforge/rules/*.md
                                  (fallback: <ws>/AGENTS.md)

The workspace is selectable and persisted in ~/.config/sparkforge/config.json.
No secret ever belongs here.
"""

import json
import os

REPO = os.path.dirname(os.path.abspath(__file__))
MAX_BYTES = int(os.environ.get("SPARKFORGE_RULES_MAX", str(32 * 1024)))


def _config_dir():
    return os.environ.get("SPARKFORGE_CONFIG_DIR") or \
        os.path.join(os.path.expanduser("~"), ".config", "sparkforge")


def global_rules_path():
    return os.path.join(_config_dir(), "RULES.md")


def global_agents_path():
    return os.path.join(_config_dir(), "AGENTS.md")


def _config_file():
    return os.path.join(_config_dir(), "config.json")


def get_workspace():
    """The selected project root (config.json, else SPARKFORGE_WORKSPACE, else repo)."""
    try:
        with open(_config_file(), "r", encoding="utf-8") as f:
            ws = (json.load(f) or {}).get("workspace")
        if ws and os.path.isdir(ws):
            return ws
    except OSError:
        pass
    except Exception:  # noqa: BLE001 — a bad config must not break anything
        pass
    return os.environ.get("SPARKFORGE_WORKSPACE") or REPO


def check_dir(path):
    """Normalise + validate an existing directory; returns the abs path or None."""
    raw = (path or "").strip()
    if not raw:
        return None
    p = os.path.abspath(os.path.expanduser(raw))
    return p if os.path.isdir(p) else None


def resolve_workspace(sess=None):
    """The workspace for a turn: a session's own folder, else the global default.

    Precedence: session["workspace"] (if it still exists) -> config.json -> env -> repo.
    """
    if isinstance(sess, dict):
        ws = check_dir(sess.get("workspace"))
        if ws:
            return ws
    return get_workspace()


def set_workspace(path):
    """Persist the GLOBAL default workspace (must be an existing directory)."""
    raw = (path or "").strip()
    real = check_dir(raw)
    if not real:
        return {"ok": False, "error": "cartella inesistente: %s" % (raw or "(vuoto)")}
    path = real
    cfg_dir = _config_dir()
    os.makedirs(cfg_dir, exist_ok=True)
    cfg = {}
    try:
        with open(_config_file(), "r", encoding="utf-8") as f:
            cfg = json.load(f) or {}
    except Exception:  # noqa: BLE001
        cfg = {}
    cfg["workspace"] = path
    tmp = _config_file() + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)
    os.replace(tmp, _config_file())
    return {"ok": True, "workspace": path}


def project_dir(ws=None):
    return os.path.join(ws or get_workspace(), ".sparkforge")


def project_rules_path(ws=None):
    return os.path.join(project_dir(ws), "RULES.md")


def project_agents_path(ws=None):
    return os.path.join(ws or get_workspace(), "AGENTS.md")


def _read(path):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return ""


def _collect_scope(native, agents, extra_dir=None):
    """(text, files): prefer the native RULES.md, else the AGENTS.md fallback."""
    files, parts = [], []
    if os.path.isfile(native):
        files.append(native)
        parts.append(_read(native))
        if extra_dir and os.path.isdir(extra_dir):
            for fn in sorted(os.listdir(extra_dir)):
                if fn.endswith(".md"):
                    files.append(os.path.join(extra_dir, fn))
                    parts.append(_read(os.path.join(extra_dir, fn)))
    elif os.path.isfile(agents):
        files.append(agents)
        parts.append(_read(agents))
    text = "\n\n".join(p.strip() for p in parts if p and p.strip())
    return text, files


def collect(ws=None):
    """Everything the model would see: global + project rules and their files.

    `ws` selects the project root (defaults to the global workspace).
    """
    gtext, gfiles = _collect_scope(global_rules_path(), global_agents_path())
    ws = ws or get_workspace()
    ptext, pfiles = _collect_scope(project_rules_path(ws), project_agents_path(ws),
                                   extra_dir=os.path.join(project_dir(ws), "rules"))
    return {
        "workspace": ws,
        "global": {"text": gtext, "files": gfiles, "path": global_rules_path()},
        "project": {"text": ptext, "files": pfiles, "path": project_rules_path(ws)},
        "total_chars": len(gtext) + len(ptext),
    }


def rules_block(max_bytes=None, ws=None):
    """The prompt block (global then project, capped). Empty string when none."""
    cap = max_bytes or MAX_BYTES
    c = collect(ws)
    chunks = []
    if c["global"]["text"]:
        chunks.append("### GLOBAL rules (user, all projects)\n" + c["global"]["text"])
    if c["project"]["text"]:
        chunks.append("### PROJECT rules (workspace: %s)\n" % c["workspace"]
                      + c["project"]["text"])
    if not chunks:
        return ""
    block = "\n\n".join(chunks)
    if len(block) > cap:
        keep = max(0, cap - 16)
        block = block[:keep] + "\n… [troncate]"
    return block


def prompt_paths(ws=None):
    """The four rule-file locations the model should know (JAG-125).

    Any value shown to the model must be an ABSOLUTE path so it can `cat`/edit
    the file directly, instead of guessing where its own rules live.
    """
    ws = ws or get_workspace()
    return {
        "workspace": ws,
        "global_rules": global_rules_path(),
        "global_fallback": global_agents_path(),
        "project_rules": project_rules_path(ws),
        "project_fallback": project_agents_path(ws),
        "project_extra_dir": os.path.join(project_dir(ws), "rules"),
    }


def rules_prompt_block(max_bytes=None, ws=None):
    """Prompt block that ALWAYS carries the rule-file paths (JAG-125).

    Unlike `rules_block` (empty when no rules), this always renders the header
    with the absolute paths of the global + project rule files and their
    AGENTS.md fallbacks, so the agent knows WHERE its instructions live and can
    read or edit them with the fs tools. The rules text, when present, follows.
    """
    cap = max_bytes or MAX_BYTES
    c = collect(ws)
    pp = prompt_paths(c["workspace"])

    def _scope(title, sc, fallback, extra=None):
        head = ("### %s\n- file: %s\n- AGENTS.md fallback: %s\n"
                % (title, sc["path"], fallback))
        if extra:
            head += "- extra: %s/*.md\n" % extra
        head += "- loaded: %s\n" % (", ".join(sc["files"]) or "(none yet)")
        body = (sc["text"] or "").strip()
        return head + (body if body else "_(no rules set here yet)_")

    intro = ("## Rules on disk (global + project)\n"
             "Your standing rules are real files; read or edit them with the fs "
             "tools. Global rules apply to every project; project rules override "
             "them on conflict.\n"
             "- GLOBAL file: %s   (AGENTS.md fallback: %s)\n"
             "- PROJECT file: %s   (AGENTS.md fallback: %s)\n"
             "- PROJECT extra: %s/*.md\n"
             % (pp["global_rules"], pp["global_fallback"],
                pp["project_rules"], pp["project_fallback"], pp["project_extra_dir"]))
    chunks = [
        _scope("GLOBAL rules (user, all projects)", c["global"], pp["global_fallback"]),
        _scope("PROJECT rules (workspace: %s)" % c["workspace"], c["project"],
               pp["project_fallback"], pp["project_extra_dir"]),
    ]
    block = intro + "\n" + "\n\n".join(chunks)
    if len(block) > cap:
        keep = max(0, cap - 16)
        block = block[:keep] + "\n… [troncate]"
    return block


def save(scope, content, ws=None):
    """Write the global or project RULES.md atomically. scope in {global,project}."""
    if scope == "global":
        path = global_rules_path()
    elif scope == "project":
        path = project_rules_path(ws or get_workspace())
    else:
        return {"ok": False, "error": "scope deve essere 'global' o 'project'"}
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(content or "")
    os.replace(tmp, path)
    return {"ok": True, "scope": scope, "path": path, "chars": len(content or "")}


def status(ws=None):
    """UI-friendly snapshot: paths, existence and sizes for both scopes."""
    c = collect(ws)
    def _scope(key, path, files):
        return {"path": path, "exists": os.path.isfile(path),
                "chars": len(c[key]["text"]), "text": c[key]["text"], "files": files}
    return {
        "workspace": c["workspace"],
        "config_dir": _config_dir(),
        "global": _scope("global", global_rules_path(), c["global"]["files"]),
        "project": _scope("project", c["project"]["path"], c["project"]["files"]),
        "total_chars": c["total_chars"],
    }
