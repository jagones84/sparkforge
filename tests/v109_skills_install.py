#!/usr/bin/env python3
"""v0.9.17 acceptance — skills install (zip) + slash usage (JAG-109)."""
import io
import os
import sys
import tempfile
import zipfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
tmp = tempfile.mkdtemp(prefix="sf-skills-")
os.environ["SPARKFORGE_SESSIONS_DIR"] = os.path.join(tmp, "sessions")
os.environ["SPARKFORGE_DB"] = os.path.join(tmp, "events.db")
os.environ["SPARKFORGE_GRAPH_DIR"] = os.path.join(tmp, "graphs")
os.makedirs(os.environ["SPARKFORGE_SESSIONS_DIR"], exist_ok=True)
os.makedirs(os.environ["SPARKFORGE_GRAPH_DIR"], exist_ok=True)
os.environ.pop("SPARKFORGE_SKILLS_LOCAL_DIR", None)
sys.path.insert(0, REPO)

import skills  # noqa: E402

# isolate the skills tree in the temp dir
skills.SKILLS_DIR = os.path.join(tmp, "skills")
os.makedirs(skills.SKILLS_DIR, exist_ok=True)

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


def make_zip(entries):
    """entries: {path: bytes|str}. Returns zip bytes."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for path, data in entries.items():
            if isinstance(data, str):
                data = data.encode("utf-8")
            z.writestr(path, data)
    return buf.getvalue()


SKILL_MD = "---\nname: demo\ndescription: a demo skill\n---\n# Demo\nDo the thing.\n"

# S1 install a valid zip -> shows up with local:true
z = make_zip({"my-skill/SKILL.md": SKILL_MD, "my-skill/scripts/x.sh": "echo hi\n"})
r = skills.install_zip(z, name="demo")
check("S1 install ok", r.get("ok") is True, str(r))
found = [s for s in skills.list_skills(reload=True) if s["name"] == "demo"]
check("S1 listed", len(found) == 1, str(found))
check("S1 local flag", bool(found) and found[0]["local"] is True,
      str(found[0].get("local")) if found else "missing")
check("S1 skill.md at root",
      os.path.isfile(os.path.join(skills._local_dir(), "demo", "SKILL.md")))

total = len(results)
passed = sum(results)
print("%d/%d" % (passed, total))
sys.exit(0 if passed == total else 1)
