#!/usr/bin/env python3
"""SparkForge skills loader (v0.7.1) — discover and read agent skills.

A skill is any directory containing a SKILL.md under `skills/<category>/<name>`.
The `skills/` tree holds symlinks into the user's skill distribution
(skills-autodist-skill), so every category is live without copying files.

API:
  list_skills()            -> [{name, category, path, title, description}]
  get_skill(name)          -> full SKILL.md text (or None)
  skills_context()         -> compact block for the agent system prompt
"""

import os
import re

REPO = os.path.dirname(os.path.abspath(__file__))
SKILLS_DIR = os.path.join(REPO, "skills")

_cache = {"ts": 0, "skills": []}


def _parse_skill_md(text, fallback_name):
    """Extract (title, description) from a SKILL.md (YAML frontmatter or headings)."""
    title, desc = fallback_name, ""
    body = text
    fm = re.match(r"\A---\s*\n(.*?)\n---\s*\n", text, re.S)
    if fm:
        body = text[fm.end():]
        m = re.search(r"^name:\s*(.+?)\s*$", fm.group(1), re.M)
        if m:
            title = m.group(1).strip()
        m = re.search(r"^description:\s*(.+?)\s*$", fm.group(1), re.M | re.S)
        if m:
            desc = re.sub(r"\s+", " ", m.group(1)).strip()
    m = re.match(r"\s*#\s+(.+?)\s*$", body, re.M)
    if m and title == fallback_name:
        title = m.group(1)
    if not desc:
        for line in body.splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                desc = re.sub(r"\s+", " ", line)[:200]
                break
    return title, desc


def list_skills(reload=False):
    """Scan skills/<category>/<name>/SKILL.md; returns cached entries."""
    if os.path.exists(SKILLS_DIR):
        mt = os.stat(SKILLS_DIR).st_mtime
        if not reload and _cache["skills"] and _cache["ts"] == mt:
            return _cache["skills"]
    skills = []
    if os.path.isdir(SKILLS_DIR):
        for cat in sorted(os.listdir(SKILLS_DIR)):
            cat_dir = os.path.join(SKILLS_DIR, cat)
            if not os.path.isdir(cat_dir):
                continue
            for name in sorted(os.listdir(cat_dir)):
                sd = os.path.join(cat_dir, name)
                sp = os.path.join(sd, "SKILL.md")
                if os.path.isfile(sp):
                    try:
                        with open(sp, "r", encoding="utf-8", errors="replace") as f:
                            text = f.read(8192)
                    except OSError:
                        continue
                    title, desc = _parse_skill_md(text, name)
                    skills.append({"name": name, "category": cat,
                                   "path": os.path.relpath(sp, REPO),
                                   "title": title, "description": desc})
    if os.path.exists(SKILLS_DIR):
        _cache.update(ts=os.stat(SKILLS_DIR).st_mtime, skills=skills)
    return skills


def get_skill(name):
    """Full SKILL.md content for a skill (matched by directory name)."""
    for s in list_skills():
        if s["name"] == name:
            with open(os.path.join(REPO, s["path"]), "r",
                      encoding="utf-8", errors="replace") as f:
                return {"ok": True, **s, "content": f.read(65536)}
    return None


def skills_context(max_chars=2200):
    """Compact skills block injected into the agent's system prompt."""
    skills = list_skills()
    if not skills:
        return "Skills: none found in %s." % SKILLS_DIR
    cats = {}
    for s in skills:
        cats.setdefault(s["category"], []).append(s["name"])
    lines = ["Skills (use the `skills` tool: {\"action\":\"list\"} for details or "
             "{\"action\":\"read\",\"name\":\"<name>\"} to load a SKILL.md and "
             "follow its instructions):"]
    for cat in sorted(cats):
        lines.append("  %s: %s" % (cat, ", ".join(cats[cat])))
    out = "\n".join(lines)
    return out if len(out) <= max_chars else out[:max_chars] + "\n…[truncated]"