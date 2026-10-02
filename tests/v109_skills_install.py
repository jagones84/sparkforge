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

# S2 SKILL.md obbligatorio (assente) -> errore, nessun residuo
z = make_zip({"my-skill/readme.txt": "no skill here\n"})
r = skills.install_zip(z, name="nofile")
check("S2 missing SKILL.md rejected", "error" in r, str(r))
check("S2 no residue", not os.path.exists(os.path.join(skills._local_dir(), "nofile")))

# S3 zip-slip rifiutato
z = make_zip({"my-skill/SKILL.md": SKILL_MD, "my-skill/../../evil.txt": "boom"})
r = skills.install_zip(z, name="slip")
check("S3 zip-slip rejected", "error" in r, str(r))
check("S3 nothing outside", not os.path.exists(os.path.join(tmp, "evil.txt")) and
      not os.path.exists(os.path.join(skills.SKILLS_DIR, "evil.txt")))

# S4 symlink rifiutato
buf = io.BytesIO()
with zipfile.ZipFile(buf, "w") as zf:
    zf.writestr("my-skill/SKILL.md", SKILL_MD)
    info = zipfile.ZipInfo("my-skill/link")
    info.external_attr = (0o120777 << 16)  # symlink
    zf.writestr(info, "/etc/passwd")
r = skills.install_zip(buf.getvalue(), name="sym")
check("S4 symlink rejected", "error" in r, str(r))

# S5 cap superato (compresso)
os.environ["SPARKFORGE_SKILL_MAX_ZIP"] = "50"
z = make_zip({"my-skill/SKILL.md": SKILL_MD})
r = skills.install_zip(z, name="big")
check("S5 oversize rejected", "error" in r, str(r))
os.environ.pop("SPARKFORGE_SKILL_MAX_ZIP", None)

# nome dedotto dal frontmatter (name: demo)
z = make_zip({"whatever/SKILL.md": SKILL_MD})
r = skills.install_zip(z, name=None, overwrite=True)
check("Sx name from frontmatter", r.get("name") == "demo", str(r))

# S6 collisione senza overwrite -> errore; con overwrite -> ok
z = make_zip({"a/SKILL.md": SKILL_MD})
r = skills.install_zip(z, name="demo")
check("S6 conflict without overwrite", "error" in r, str(r))
r = skills.install_zip(z, name="demo", overwrite=True)
check("S6 overwrite ok", r.get("ok") is True, str(r))

# S7 una skill di sistema (categoria dev) non viene toccata; il locale è separato
sysdir = os.path.join(skills.SKILLS_DIR, "dev", "devonly")
os.makedirs(sysdir, exist_ok=True)
with open(os.path.join(sysdir, "SKILL.md"), "w", encoding="utf-8") as f:
    f.write(SKILL_MD)
z = make_zip({"a/SKILL.md": SKILL_MD})
skills.install_zip(z, name="sysonly", overwrite=True)
check("S7 system dir untouched", os.path.isfile(os.path.join(sysdir, "SKILL.md")))
check("S7 local created separately", skills.is_local("sysonly"))

# S8 remove: locale ok, non locale rifiutato
r = skills.remove("sysonly")
check("S8 remove local ok", r.get("ok") is True and not skills.is_local("sysonly"), str(r))
r = skills.remove("devonly")
check("S8 remove non-local rejected", "error" in r, str(r))

# S10 la route API esiste nel sorgente e la lista porta il flag local
src = open(os.path.join(REPO, "api_v02.py"), encoding="utf-8").read()
check("S10 GET /api/skills route present", '"/api/skills"' in src)
check("S10 DELETE route present", '"/api/skills/' in src and "DELETE" in src)
lst = skills.list_skills(reload=True)
check("S10 list has local flag", all("local" in s for s in lst), str(lst[:1]))

# S11 l'upload raw è gestito in server.py (branch zip) e delega a skills.install_zip
srv = open(os.path.join(REPO, "server.py"), encoding="utf-8").read()
check("S11 raw zip branch present",
      '"/api/skills/install"' in srv and "application/zip" in srv)
check("S11 api helper present",
      "install_skill_raw" in open(os.path.join(REPO, "api_v02.py"),
                                  encoding="utf-8").read())

total = len(results)
passed = sum(results)
print("%d/%d" % (passed, total))
sys.exit(0 if passed == total else 1)
