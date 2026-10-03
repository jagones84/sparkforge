#!/usr/bin/env python3
"""Registro di sezioni del system prompt (JAG-128A).

Il prompt NON e' un monolite: e' una lista ordinata di sezioni. Ogni sezione e':
  - kind="static"  -> testo di default (default + overlay file, additivo)
  - kind="dynamic" -> provider in codice, generato a runtime (tools/skills/...)

Overlay file (ADDITIVI, non sostitutivi):
  - globale:  ~/.config/sparkforge/prompt.d/<NN>-<id>.md
  - progetto: <workspace>/.sparkforge/prompt.d/<NN>-<id>.md
In caso di CONTRADDIZIONE vince il livello piu' specifico:
  PROGETTO > GLOBALE > DEFAULT.
"""
import glob
import os

GLOBAL_DDIR = os.path.expanduser(os.path.join("~", ".config", "sparkforge", "prompt.d"))

# Ordine e natura delle sezioni. `<NN>-` nei file ordina gli addendum via glob.
SECTIONS = [
    {"id": "identity",      "order": 10, "kind": "static"},
    {"id": "prompt-map",    "order": 15, "kind": "static"},
    {"id": "self-summary",  "order": 20, "kind": "dynamic"},
    {"id": "tools",         "order": 30, "kind": "dynamic"},
    {"id": "rules-policy",  "order": 40, "kind": "static"},
    {"id": "rules",         "order": 41, "kind": "dynamic"},
    {"id": "skills-policy", "order": 50, "kind": "static"},
    {"id": "skills",        "order": 51, "kind": "dynamic"},
    {"id": "memory-policy", "order": 60, "kind": "static"},
    {"id": "memory",        "order": 61, "kind": "dynamic"},
    {"id": "capability",    "order": 70, "kind": "static"},
    {"id": "state",         "order": 90, "kind": "dynamic"},
]

# sezioni statiche i cui default vivono in server.py (lazy import: niente cicli)
_STATIC_ATTRS = {
    "identity": "SYSTEM_PROMPT",
    "rules-policy": "RULES_POLICY",
    "skills-policy": "SKILLS_POLICY",
    "memory-policy": "MEMORY_POLICY",
}


CAPABILITY_RULE = (
    "## Capability questions\n"
    "When the user asks about YOUR OWN capabilities \u2014 which tools you have, "
    "whether a tool exists, where your rules or memory live, what you can do \u2014 "
    "answer FROM YOUR PROMPT: the `Tool registry` block above, the tool `self`, or "
    "skills{action:'list'}. NEVER run shell/git (ls, find, git status) to answer a "
    "question about yourself: that inspects the machine, not you."
)


def _manifest_text():
    pretty = ", ".join("%s(%s)" % (s["id"], s["kind"]) for s in SECTIONS)
    return (
        "## How you are built (prompt map)\n"
        "Your system prompt is an ordered list of sections; some are generated at "
        "runtime, some are text you can EXTEND with files (adding, never replacing). "
        "In case of CONTRADICTION the more specific level wins: PROJECT > GLOBAL > DEFAULT.\n"
        "- global section addenda: %s/<NN>-<id>.md\n"
        "- project section addenda: <workspace>/.sparkforge/prompt.d/<NN>-<id>.md\n"
        "- sections: %s" % (GLOBAL_DDIR, pretty)
    )


def prompt_map_text():
    """Public wrapper: the prompt-map (manifest) section text."""
    return _manifest_text()


def capability_text():
    """Public wrapper: the capability rule section text."""
    return CAPABILITY_RULE


def project_ddir(ws):
    return os.path.join(ws or "", ".sparkforge", "prompt.d")


def _read(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read().strip()
    except OSError:
        return ""


def _section_id(filename):
    stem = filename[:-3] if filename.endswith(".md") else filename
    head, sep, tail = stem.partition("-")
    if sep and head.isdigit():
        return tail
    return stem


def _addenda(base_dir):
    """{section_id: text} dagli overlay <NN>-<id>.md (ordine alfabetico)."""
    out = {}
    if not base_dir:
        return out
    for p in sorted(glob.glob(os.path.join(base_dir, "*.md"))):
        sid = _section_id(os.path.basename(p))
        if not sid:
            continue
        text = _read(p)
        out[sid] = (out[sid] + "\n" + text) if sid in out else text
    return out


def _static_text(sid):
    if sid == "capability":
        return CAPABILITY_RULE
    if sid == "prompt-map":
        return _manifest_text()
    from . import server
    return getattr(server, _STATIC_ATTRS.get(sid, ""), "") or ""


def render_sections(sess=None, ws=None, tool_ctx=None):
    """Monta il prompt finale: per ogni sezione, default + globale + progetto."""
    g = _addenda(GLOBAL_DDIR)
    p = _addenda(project_ddir(ws)) if ws else {}
    parts_out = []
    for sec in sorted(SECTIONS, key=lambda s: s["order"]):
        sid = sec["id"]
        if sec["kind"] == "static":
            base = _static_text(sid)
        else:
            base = _PROVIDERS.get(sid, lambda *a: "")(sess, ws, tool_ctx)
        parts = [x.strip() for x in (base or "", g.get(sid, ""), p.get(sid, ""))
                 if x and x.strip()]
        if parts:
            parts_out.append("\n".join(parts))
    return "\n\n".join(parts_out)


def _provider_self_summary(sess, ws, ctx):
    try:
        from . import server
        return server.self_summary()
    except Exception:  # noqa: BLE001
        return ""


def _provider_tools(sess, ws, ctx):
    if ctx:
        return ctx
    try:
        from . import server
        return server._tool_context()
    except Exception:  # noqa: BLE001
        return ""


def _provider_rules(sess, ws, ctx):
    try:
        from . import rules
        return rules.rules_prompt_block(ws=ws or rules.resolve_workspace(sess))
    except Exception:  # noqa: BLE001
        return ""


def _provider_skills(sess, ws, ctx):
    try:
        from . import skills
        # JAG-163: name + one-line description, budgeted so a large library is
        # still capped instead of flooding the prompt.
        return skills.skills_context(max_chars=8000)
    except Exception:  # noqa: BLE001
        return ""


def _provider_memory(sess, ws, ctx):
    block = ""
    try:
        from . import memory
        lessons = memory.governed_query(kind="agent.note", limit=6)
        instr = ["- " + str(r.get("content", "")).strip()
                 for r in lessons if str(r.get("content", "")).strip()]
        if instr:
            block = "\nLessons from past sessions (self-improvement):\n" + "\n".join(instr)
        core = memory.core_read().strip()
        if core:
            block += ("\n\n## Core memory (always visible \u2014 edit with "
                      "memory{action:'set_core'})\n" + core)
    except Exception:  # noqa: BLE001
        pass
    return block


def _provider_state(sess, ws, ctx):
    try:
        from . import server
        return ("Harness state (your persistent task list):\n"
                + server.context_summary(session_id=(sess or {}).get("id")))
    except Exception:  # noqa: BLE001
        return ""


_PROVIDERS = {
    "self-summary": _provider_self_summary,
    "tools": _provider_tools,
    "rules": _provider_rules,
    "skills": _provider_skills,
    "memory": _provider_memory,
    "state": _provider_state,
}
