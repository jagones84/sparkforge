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

import io
import os
import re
import shutil
import stat
import tempfile
import zipfile

REPO = os.path.dirname(os.path.abspath(__file__))
SKILLS_DIR = os.path.join(REPO, "skills")

LOCAL_CATEGORY = "local"

_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")


def _local_dir():
    """Directory delle skill caricate dall'utente (gitignored)."""
    return os.environ.get("SPARKFORGE_SKILLS_LOCAL_DIR") or \
        os.path.join(SKILLS_DIR, LOCAL_CATEGORY)


def _max_zip():
    return int(os.environ.get("SPARKFORGE_SKILL_MAX_ZIP", str(20 * 1024 * 1024)))


def _max_unzip():
    return int(os.environ.get("SPARKFORGE_SKILL_MAX_UNZIP", str(60 * 1024 * 1024)))


def _max_files():
    return int(os.environ.get("SPARKFORGE_SKILL_MAX_FILES", "500"))


def _safe_name(name):
    name = (name or "").strip().lower()
    return name if _NAME_RE.match(name) else None


def _frontmatter_name(text):
    fm = re.match(r"\A---\s*\n(.*?)\n---\s*\n", text, re.S)
    if fm:
        m = re.search(r"^name:\s*(.+?)\s*$", fm.group(1), re.M)
        if m:
            return m.group(1).strip()
    return None


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
                                   "title": title, "description": desc,
                                   "local": cat == LOCAL_CATEGORY})
    if os.path.exists(SKILLS_DIR):
        _cache.update(ts=os.stat(SKILLS_DIR).st_mtime, skills=skills)
    return skills


def install_zip(data, name=None, overwrite=False):
    """Estrae uno zip di skill in _local_dir()/<nome>. Ritorna {ok,...} o {error}."""
    if not data:
        return {"error": "empty zip body"}
    if len(data) > _max_zip():
        return {"error": "zip too large (max %d bytes)" % _max_zip()}
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        return {"error": "not a valid zip archive"}
    with zf:
        infos = zf.infolist()
        if len(infos) > _max_files():
            return {"error": "too many files (max %d)" % _max_files()}
        if sum(i.file_size for i in infos) > _max_unzip():
            return {"error": "uncompressed too large (max %d bytes)" % _max_unzip()}
        for i in infos:
            if (i.external_attr >> 16) & 0o170000 == stat.S_IFLNK:
                return {"error": "zip contains a symlink: %s" % i.filename}
        raw_names = [i.filename.replace("\\", "/").strip("/")
                     for i in infos if i.filename.strip("/")]
        tops = {n.split("/")[0] for n in raw_names}
        strip = None
        if len(tops) == 1:
            only = next(iter(tops))
            if only not in raw_names:  # compare solo come prefisso di directory
                strip = only
        local = _local_dir()
        os.makedirs(local, exist_ok=True)
        stage = tempfile.mkdtemp(prefix=".install-", dir=local)
        try:
            root = os.path.realpath(stage)
            for i in infos:
                parts = [p for p in i.filename.replace("\\", "/").split("/")
                         if p not in ("", ".")]
                if any(p == ".." for p in parts):
                    return {"error": "path traversal in zip: %s" % i.filename}
                if strip and parts and parts[0] == strip:
                    parts = parts[1:]
                if not parts:
                    continue
                dest = os.path.join(stage, *parts)
                real = os.path.realpath(dest)
                if real != root and not real.startswith(root + os.sep):
                    return {"error": "unsafe path in zip: %s" % i.filename}
                if i.is_dir():
                    os.makedirs(dest, exist_ok=True)
                else:
                    os.makedirs(os.path.dirname(dest), exist_ok=True)
                    with zf.open(i) as src, open(dest, "wb") as out:
                        shutil.copyfileobj(src, out)
            if not os.path.isfile(os.path.join(stage, "SKILL.md")):
                return {"error": "SKILL.md not found at skill root"}
            if name is None:
                with open(os.path.join(stage, "SKILL.md"), "r",
                          encoding="utf-8", errors="replace") as f:
                    name = _frontmatter_name(f.read())
            safe = _safe_name(name)
            if not safe:
                return {"error": "invalid skill name: %r" % name}
            target = os.path.join(local, safe)
            if os.path.exists(target):
                if not overwrite:
                    return {"error": "skill '%s' already exists (use overwrite)" % safe}
                shutil.rmtree(target)
            os.replace(stage, target)
            stage = None
            list_skills(reload=True)
            return {"ok": True, "name": safe, "category": LOCAL_CATEGORY,
                    "path": os.path.relpath(target, REPO)}
        finally:
            if stage and os.path.isdir(stage):
                shutil.rmtree(stage, ignore_errors=True)


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