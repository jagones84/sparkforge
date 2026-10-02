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
        if sid:
            out[sid] = _read(p)
    return out


def _static_text(sid):
    if sid == "capability":
        return CAPABILITY_RULE
    if sid == "prompt-map":
        return _manifest_text()
    import server
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
