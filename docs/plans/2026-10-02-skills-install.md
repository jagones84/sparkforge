# Skills: install via zip + uso con `/` — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Permettere all'utente di installare una skill caricando uno zip (categoria locale `skills/local/`) e di usarla dalla chat digitando `/`, con iniezione della `SKILL.md` fatta lato server.

**Architecture:** Tutta la logica sta nel server. L'engine resta [skills.py](file:///z:/Repositories/sparkforge/skills.py) (scoperta + estrazione sicura zip). Gli endpoint `/api/skills*` vivono in [api_v02.py](file:///z:/Repositories/sparkforge/api_v02.py); l'upload raw zip è letto in [server.py](file:///z:/Repositories/sparkforge/server.py) (stesso schema di `/api/voice/stt`). L'iniezione `/` avviene nel punto unico di assemblaggio del prompt (`assemble_turn`). WebUI è solo renderer.

**Tech Stack:** Python 3 stdlib (`json`, `zipfile`, `io`, `os`, `shutil`, `tempfile`, `stat`, `re`), `http.server`. Test standalone `python3 tests/<file>.py` (stile repo: stampa PASS/FAIL, exit code). Nessun framework, nessuna dipendenza.

**Spec:** [docs/specs/2026-10-02-skills-install-design.md](file:///z:/Repositories/sparkforge/docs/specs/2026-10-02-skills-install-design.md)

**Comandi utili (cwd = `/home/jagones/Repositories/sparkforge` sul DGX):**
- Test: `python3 tests/v109_skills_install.py`
- Regressione: `python3 tests/v071_skills_pmcp.py`
- Riavvio server: `bash trash/restart-server.sh` (poi verificare che il pid in ascolto su :8790 cambi)
- Modifica file su DGX: scrivere lo script da Windows, poi `ssh dgx "sed -i 's/\r$//' <file>"` prima di eseguirlo.

**Convenzione**: dopo ogni task, `git add <file> && git commit`. Ogni task produce software funzionante e testabile da solo.

---

## File Structure

- **Modify** `skills.py` — engine: flag `local`, `_local_dir()`, `install_zip()`, `remove()`, `is_local()`. Resta l'unica fonte di scoperta skill.
- **Modify** `api_v02.py` — `GET /api/skills`, `GET /api/skills/<nome>`, `DELETE /api/skills/<nome>`, e l'helper `install_skill_raw(bytes, name, overwrite)`.
- **Modify** `server.py` — branch raw `application/zip` → `POST /api/skills/install`; `_apply_skill_slash()` chiamato in `assemble_turn`.
- **Modify** `webui/index.html` — pannello Skills (upload zip, lista, delete) + autocomplete `/` nella chat.
- **Modify** `.gitignore` — `skills/local/`.
- **Create** `tests/v109_skills_install.py` — accettazione (S1–S10).

---

## Task 1: Engine — scoperta con flag `local` + `_local_dir()` + install happy-path

**Files:**
- Modify: `skills.py` (import in testa; nuove costanti/funzioni; `list_skills`)
- Test: `tests/v109_skills_install.py`

- [ ] **Step 1: Write the failing test**

Crea `tests/v109_skills_install.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/v109_skills_install.py`
Expected: FAIL/errore — `AttributeError: module 'skills' has no attribute 'install_zip'` (o simili).

- [ ] **Step 3: Write minimal implementation**

In `skills.py`, aggiungi gli import in testa (dopo `import re`):

```python
import io
import shutil
import stat
import tempfile
import zipfile
```

Aggiungi le costanti e gli helper (dopo `SKILLS_DIR = ...`):

```python
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
```

In `list_skills()`, aggiungi il flag `local` all'append:

```python
                    skills.append({"name": name, "category": cat,
                                   "path": os.path.relpath(sp, REPO),
                                   "title": title, "description": desc,
                                   "local": cat == LOCAL_CATEGORY})
```

Aggiungi `install_zip` (dopo `list_skills`, prima di `get_skill`):

```python
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
```

Aggiungi l'helper frontmatter (dopo `_safe_name`):

```python
def _frontmatter_name(text):
    fm = re.match(r"\A---\s*\n(.*?)\n---\s*\n", text, re.S)
    if fm:
        m = re.search(r"^name:\s*(.+?)\s*$", fm.group(1), re.M)
        if m:
            return m.group(1).strip()
    return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 tests/v109_skills_install.py`
Expected: `4/4` con tutte le righe PASS.

- [ ] **Step 5: Commit**

```bash
git add skills.py tests/v109_skills_install.py
git commit -m "JAG-109 skill install: engine zip (happy path) + local flag"
```

---

## Task 2: Engine — sicurezza zip (slip, symlink, cap, SKILL.md obbligatorio)

**Files:**
- Modify: `skills.py` (già coperto dall'implementazione del Task 1)
- Test: `tests/v109_skills_install.py` (aggiungi S2–S5)

- [ ] **Step 1: Write the failing test**

In `tests/v109_skills_install.py`, inserisci **prima** dello `total = ...` finale:

```python
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
```

- [ ] **Step 2: Run test to verify it fails or passes**

Run: `python3 tests/v109_skills_install.py`
Expected: se il Task 1 è completo, questi PASSano già (l'implementazione è stata scritta per coprirli). Se qualche PASS non c'è, correggi `install_zip`. Non procedere finché non sono tutti PASS.

- [ ] **Step 3: (nessuna implementazione nuova)**

Se tutti PASSano, l'implementazione del Task 1 è sufficiente. Se un caso fallisce, la correzione va in `skills.py` (es. ordine dei controlli: symlink e cap **prima** dell'estrazione).

- [ ] **Step 4: Run test**

Run: `python3 tests/v109_skills_install.py`
Expected: `10/10` PASS (4 del Task 1 + 6 di questo task).

- [ ] **Step 5: Commit**

```bash
git add tests/v109_skills_install.py
git commit -m "JAG-109 skill install: security cases (slip/symlink/oversize/SKILL.md)"
```

---

## Task 3: Engine — overwrite, remove, is_local, nome da frontmatter

**Files:**
- Modify: `skills.py` (aggiungi `remove`, `is_local`)
- Test: `tests/v109_skills_install.py` (aggiungi S6–S8 + nome da frontmatter)

- [ ] **Step 1: Write the failing test**

Aggiungi prima di `total = ...`:

```python
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

# S7 overwrite non tocca le skill di sistema (categoria diversa)
sysdir = os.path.join(skills.SKILLS_DIR, "dev", "sysskill")
os.makedirs(sysdir, exist_ok=True)
with open(os.path.join(sysdir, "SKILL.md"), "w", encoding="utf-8") as f:
    f.write(SKILL_MD)
z = make_zip({"a/SKILL.md": SKILL_MD})
skills.install_zip(z, name="sysskill", overwrite=True)
check("S7 system skill untouched",
      os.path.isfile(os.path.join(sysdir, "SKILL.md")))

# S8 remove: locale ok, non locale rifiutato
r = skills.remove("demo")
check("S8 remove local ok", r.get("ok") is True and not skills.is_local("demo"), str(r))
r = skills.remove("sysskill")
check("S8 remove non-local rejected", "error" in r, str(r))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/v109_skills_install.py`
Expected: FAIL — `AttributeError: module 'skills' has no attribute 'remove'`.

- [ ] **Step 3: Write minimal implementation**

In `skills.py`, dopo `install_zip`, aggiungi:

```python
def is_local(name):
    """True se esiste una skill caricata dall'utente con questo nome."""
    safe = _safe_name(name)
    return bool(safe) and os.path.isdir(os.path.join(_local_dir(), safe))


def remove(name):
    """Rimuove una skill LOCALE. Non tocca mai le skill di sistema."""
    safe = _safe_name(name)
    if not safe:
        return {"error": "invalid name: %r" % name}
    target = os.path.join(_local_dir(), safe)
    if not os.path.isdir(target):
        return {"error": "local skill not found: %s" % safe}
    shutil.rmtree(target)
    list_skills(reload=True)
    return {"ok": True, "name": safe}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 tests/v109_skills_install.py`
Expected: `16/16` PASS (10 + 6 di questo task).

- [ ] **Step 5: Commit**

```bash
git add skills.py tests/v109_skills_install.py
git commit -m "JAG-109 skill install: overwrite/remove/is_local + frontmatter name"
```

---

## Task 4: API HTTP — GET lista/lettura, DELETE

**Files:**
- Modify: `api_v02.py` (ramo GET e ramo DELETE in `handle()`)
- Test: in-process (`tests/v109_skills_install.py` non copre HTTP; la verifica live è nel Task 8)

- [ ] **Step 1: Write the failing test**

Aggiungi un controllo di contratto direttamente sull'engine + presenza route nel sorgente (stile repo, es. `v080`):

```python
# S10 la route API esiste nel sorgente e la lista porta il flag local
src = open(os.path.join(REPO, "api_v02.py"), encoding="utf-8").read()
check("S10 GET /api/skills route present", '"/api/skills"' in src)
check("S10 DELETE route present", '"/api/skills/' in src and "DELETE" in src)
lst = skills.list_skills(reload=True)
check("S10 list has local flag", all("local" in s for s in lst), str(lst[:1]))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/v109_skills_install.py`
Expected: FAIL su "S10 GET /api/skills route present".

- [ ] **Step 3: Write minimal implementation**

In `api_v02.py`, nel ramo `if method == "GET":` (dopo la rotta `/api/mcp/clients`), aggiungi:

```python
        # --- JAG-109: skills (engine in skills.py) ---
        if path == "/api/skills":
            import skills as skills_mod
            items = skills_mod.list_skills()
            return _r(handler, 200, {"skills": items, "count": len(items),
                                     "local_dir": skills_mod._local_dir()})
        if path.startswith("/api/skills/"):
            import skills as skills_mod
            nm = path[len("/api/skills/"):]
            sk = skills_mod.get_skill(nm)
            return _r(handler, 200, sk) if sk else \
                _r(handler, 404, {"error": "skill not found: %s" % nm})
```

Nel ramo `if method == "DELETE":` (accanto alla rotta MCP), aggiungi:

```python
        # JAG-109: remove a user-installed (local) skill.
        if path.startswith("/api/skills/"):
            import skills as skills_mod
            nm = path[len("/api/skills/"):]
            res = skills_mod.remove(nm)
            _publish("skills.remove", name=nm, ok=bool(res.get("ok")))
            return _r(handler, 200 if res.get("ok") else 400, res)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 tests/v109_skills_install.py`
Expected: `19/19` PASS (16 + 3 di questo task).

- [ ] **Step 5: Commit**

```bash
git add api_v02.py tests/v109_skills_install.py
git commit -m "JAG-109 skills API: GET list/read + DELETE (local only)"
```

---

## Task 5: API HTTP — install raw zip (`POST /api/skills/install`)

**Files:**
- Modify: `api_v02.py` (nuovo helper `install_skill_raw`)
- Modify: `server.py` (branch raw in `do_POST`)

- [ ] **Step 1: Write the failing test**

```python
# S11 l'upload raw è gestito in server.py (branch zip) e delega a skills.install_zip
srv = open(os.path.join(REPO, "server.py"), encoding="utf-8").read()
check("S11 raw zip branch present",
      '"/api/skills/install"' in srv and "application/zip" in srv)
check("S11 api helper present",
      "install_skill_raw" in open(os.path.join(REPO, "api_v02.py"),
                                  encoding="utf-8").read())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/v109_skills_install.py`
Expected: FAIL su "S11 raw zip branch present".

- [ ] **Step 3: Write minimal implementation**

In `api_v02.py`, aggiungi (vicino a `update_policy`):

```python
def install_skill_raw(data, name=None, overwrite=False):
    """POST /api/skills/install — body zip grezzo. Engine: skills.install_zip."""
    import skills as skills_mod
    res = skills_mod.install_zip(data, name=name, overwrite=overwrite)
    _publish("skills.install", name=res.get("name"), ok=bool(res.get("ok")))
    return res
```

In `server.py`, in `do_POST`, **subito dopo** il branch `/api/voice/stt` (prima di `body = self._body()`), aggiungi:

```python
        # Raw skill zip upload (JAG-109) — before JSON parsing.
        if path == "/api/skills/install" and (
                ctype.startswith("application/zip") or ctype.startswith("application/x-zip")):
            n = int(self.headers.get("Content-Length") or 0)
            if not n:
                return self._send(400, {"error": "zip body required"})
            data = self.rfile.read(n)
            res = api_v02.install_skill_raw(data, name=qs.get("name"),
                                            overwrite=qs.get("overwrite") == "1")
            return self._send(200 if res.get("ok") else 400, res)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 tests/v109_skills_install.py`
Expected: `21/21` PASS (19 + 2 di questo task).

- [ ] **Step 5: Commit**

```bash
git add api_v02.py server.py tests/v109_skills_install.py
git commit -m "JAG-109 skills API: raw zip install (POST /api/skills/install)"
```

---

## Task 6: Chat — iniezione one-shot della SKILL.md con `/nome`

**Files:**
- Modify: `server.py` (`_apply_skill_slash` + chiamata in `assemble_turn`)
- Test: `tests/v109_skills_install.py`

- [ ] **Step 1: Write the failing test**

```python
# S9 /nome inietta la SKILL.md nel prompt assemblato (una sola volta)
z = make_zip({"demo-skill/SKILL.md": SKILL_MD})
skills.install_zip(z, name="demo", overwrite=True)
import server  # noqa: E402
sess = server.get_or_create_session("skill-inject")
server.append_message(sess, "user", "/demo spiegami")
msgs, _ = server.assemble_turn(sess, "/demo spiegami")
joined = "\n".join(m.get("content", "") for m in msgs)
check("S9 skill content injected", "Do the thing." in joined)
check("S9 skill directive present", "SKILL ACTIVATION" in joined)
msgs2, _ = server.assemble_turn(sess, "ciao normale")
joined2 = "\n".join(m.get("content", "") for m in msgs2)
check("S9 no inject without slash", "SKILL ACTIVATION" not in joined2)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/v109_skills_install.py`
Expected: FAIL su "S9 skill content injected".

- [ ] **Step 3: Write minimal implementation**

In `server.py`, aggiungi **prima** di `def assemble_turn(...)`:

```python
def _apply_skill_slash(message):
    """JAG-109: `/nome resto` → inietta la SKILL.md nel prompt del turno.

    Non modifica la history salvata (resta `/nome resto`); l'iniezione è
    transitoria e vale solo per questo turno. `/goal` non è toccato.
    """
    if not message or not message.startswith("/"):
        return message
    token, _, rest = message[1:].partition(" ")
    token = token.strip().lower()
    if not token or token == "goal":
        return message
    try:
        import skills as skills_mod
        sk = skills_mod.get_skill(token)
    except Exception:  # noqa: BLE001 — l'iniezione non deve mai rompere un turno
        return message
    if not sk:
        return message
    body = (sk.get("content") or "")[:20000]
    return ("SKILL ACTIVATION — '%s' (follow these instructions for this turn)\n\n"
            "%s\n\n---\nUSER: %s" % (token, body, rest.strip()))
```

In `assemble_turn`, sostituisci la riga `eff_message = message` con:

```python
    eff_message = _apply_skill_slash(message)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 tests/v109_skills_install.py`
Expected: `24/24` PASS (21 + 3 di questo task).

- [ ] **Step 5: Commit**

```bash
git add server.py tests/v109_skills_install.py
git commit -m "JAG-109 chat: one-shot SKILL.md injection for /name"
```

---

## Task 7: `.gitignore` + regressione engine

**Files:**
- Modify: `.gitignore`

- [ ] **Step 1: Aggiorna `.gitignore`**

Aggiungi in fondo:

```
# JAG-109: user-installed skills (zip upload) — never in the repo.
skills/local/
```

- [ ] **Step 2: Verifica che l'ignore funzioni**

Run: `git check-ignore -v skills/local/demo/SKILL.md || echo "NOT IGNORED"`
Expected: stampa la regola `skills/local/` (non "NOT IGNORED").

- [ ] **Step 3: Regressione engine**

Run: `python3 tests/v071_skills_pmcp.py`
Expected: tutte PASS (nessuna skill di sistema toccata).

- [ ] **Step 4: Commit**

```bash
git add .gitignore
git commit -m "JAG-109: gitignore user-installed skills (skills/local/)"
```

---

## Task 8: WebUI — pannello Skills + autocomplete `/`

**Files:**
- Modify: `webui/index.html`

- [ ] **Step 1: Aggiungi la tab e la sezione**

Nel rail (`#rail-tabs`) aggiungi accanto alle altre:

```html
      <button data-panel="skills" onclick="openPanel('skills')">Skills</button>
```

In `#panel-body` (dopo la `<section data-section="mcp" ...>`), aggiungi:

```html
      <section data-section="skills" hidden>
        <h2>Skills · installate</h2>
        <div class="card">
          <div class="remaining" id="skillsSummary">caricamento…</div>
          <div id="skillsList" style="margin-top:8px"></div>
        </div>
        <h2>Installa da zip</h2>
        <div class="card">
          <input type="file" id="skillZip" accept=".zip" style="font-size:12px">
          <input id="skillName" class="inp" placeholder="nome (opzionale · dal file)" style="width:100%;padding:6px 10px;font-size:12px;margin-top:6px">
          <label class="remaining" style="display:flex;gap:6px;align-items:center;margin-top:6px"><input type="checkbox" id="skillOverwrite"> sovrascrivi se esiste</label>
          <button class="ghost" onclick="installSkillZip()" style="margin-top:8px">installa</button>
          <div id="skillResult" class="remaining" style="margin-top:6px"></div>
          <div class="remaining" style="margin-top:6px">installate in skills/local/ (fuori dal repo)</div>
        </div>
      </section>
```

- [ ] **Step 2: Aggiungi il JS del pannello + autocomplete**

Prima di `function openPanel(name)`, aggiungi:

```javascript
/* ---- JAG-109: skills panel + '/' autocomplete (engine = /api/skills) ---- */
let _skillsCache = [];
async function loadSkills() {
  try {
    const d = await api("GET", "/api/skills");
    _skillsCache = d.skills || [];
    $("skillsSummary").textContent = _skillsCache.length + " skill · locali: " +
      _skillsCache.filter(s => s.local).length;
    const box = $("skillsList"); box.innerHTML = "";
    _skillsCache.forEach(s => {
      const row = document.createElement("div");
      row.className = "card";
      row.style.cssText = "padding:6px 8px;margin-bottom:6px;display:flex;gap:8px;align-items:center";
      const dot = document.createElement("span"); dot.textContent = s.local ? "🟢" : "🏠";
      const info = document.createElement("div"); info.style.cssText = "flex:1;min-width:0";
      const t = document.createElement("div"); t.style.fontWeight = "600"; t.textContent = s.name;
      const sub = document.createElement("div"); sub.className = "remaining";
      sub.textContent = (s.category || "") + " · " + (s.title || "");
      info.append(t, sub);
      const ins = document.createElement("button"); ins.className = "ghost"; ins.textContent = "/";
      ins.title = "usa in chat"; ins.onclick = () => { $("msg") && ($("msg").value = "/" + s.name + " "); $("msg") && $("msg").focus(); };
      row.append(dot, info, ins);
      if (s.local) {
        const del = document.createElement("button"); del.className = "ghost"; del.textContent = "🗑";
        del.onclick = async () => {
          if (!(await confirmDelete("rimuovere la skill '" + s.name + "'?"))) return;
          await api("DELETE", "/api/skills/" + encodeURIComponent(s.name));
          loadSkills();
        };
        row.appendChild(del);
      }
      box.appendChild(row);
    });
  } catch (e) { $("skillsSummary").textContent = "errore: " + e; }
}
async function installSkillZip() {
  const f = $("skillZip").files && $("skillZip").files[0];
  if (!f) { $("skillResult").textContent = "scegli un file .zip"; return; }
  const qs = new URLSearchParams();
  if ($("skillName").value.trim()) qs.set("name", $("skillName").value.trim());
  if ($("skillOverwrite").checked) qs.set("overwrite", "1");
  $("skillResult").textContent = "carico…";
  const r = await fetch("/api/skills/install?" + qs.toString(), {
    method: "POST", headers: authHeaders().set("Content-Type", "application/zip"), body: f
  }).then(x => x.json()).catch(e => ({ error: String(e) }));
  $("skillResult").textContent = r.error ? ("errore: " + r.error) : ("installata: " + r.name);
  if (!r.error) { loadSkills(); loadCtx(); }
}
function skillsAutocomplete() {
  const inp = $("msg"); if (!inp) return;
  const box = $("slashMenu");
  const v = inp.value;
  if (!v.startsWith("/") || v.includes(" ")) { box.hidden = true; return; }
  const q = v.slice(1).toLowerCase();
  const hits = _skillsCache.filter(s => s.name.toLowerCase().startsWith(q)).slice(0, 8);
  if (!hits.length) { box.hidden = true; return; }
  box.innerHTML = "";
  hits.forEach(s => {
    const li = document.createElement("div");
    li.style.cssText = "padding:6px 10px;cursor:pointer;font-size:12px";
    li.textContent = "/" + s.name + "  ·  " + (s.title || s.description || "");
    li.onclick = () => { inp.value = "/" + s.name + " "; box.hidden = true; inp.focus(); };
    box.appendChild(li);
  });
  box.hidden = false;
}
```

- [ ] **Step 3: Aggiungi il menu `/` e aggancia gli eventi**

Nel markup della chat, vicino all'input messaggio (id `msg`), aggiungi subito sopra il box input:

```html
      <div id="slashMenu" class="card" hidden style="position:absolute;bottom:100%;left:0;right:0;max-height:200px;overflow-y:auto;padding:4px 0"></div>
```

Nel bootstrap (dove si registrano gli handler), aggiungi:

```javascript
  if ($("msg")) {
    $("msg").addEventListener("input", skillsAutocomplete);
    $("msg").addEventListener("keydown", e => {
      if (e.key === "Escape" && $("slashMenu")) $("slashMenu").hidden = true;
    });
  }
  loadSkills();
```

In `openPanel`, aggiungi il branch:

```javascript
  else if (name === "skills") { loadSkills(); }
```

- [ ] **Step 4: Verifica in browser**

Riavvia il server (`bash trash/restart-server.sh`), apri la WebUI, apri il pannello **Skills**: la lista deve apparire. Digita `/` nella barra chat: compare il menu. (Dettaglio nel Task 9.)

- [ ] **Step 5: Commit**

```bash
git add webui/index.html
git commit -m "JAG-109 WebUI: skills panel (zip upload) + '/' autocomplete"
```

---

## Task 9: Verifica end-to-end + HANDOFF

**Files:**
- Modify: `.agent/HANDOFF.md` (nel repo `Repositories`, non in sparkforge)

- [ ] **Step 1: Regressione completa**

Run:
```bash
python3 -m py_compile server.py api_v02.py skills.py && \
for t in v109_skills_install v071_skills_pmcp v108_mcp_manage v107_context_display v074_context; do \
  python3 tests/$t.py | tail -n 1; done
```
Expected: `py_compile` silenzioso; ultima riga di ogni test = `N/N` con N=PASS.

- [ ] **Step 2: Verifica HTTP live**

Riavvia il server, poi con uno script Python (raw zip) verifica:
`GET /api/skills` → 200 con lista; `POST /api/skills/install?name=live-demo` con body zip → `{ok:true}`; `GET /api/skills` la contiene con `local:true`; `DELETE /api/skills/live-demo` → `{ok:true}`; `GET` non la contiene più.

- [ ] **Step 3: Verifica browser**

Nella WebUI reale: pannello Skills popolato; install di uno zip di prova; digitando `/` compare il menu con la skill; inviando `/live-demo ciao`, il messaggio parte e l'agente risponde (nessun errore in console).

- [ ] **Step 4: Aggiorna HANDOFF**

In `.agent/HANDOFF.md` (repo `Repositories`) aggiungi in testa la voce JAG-109 con: causa/obiettivo, file toccati, comandi di verifica, numeri (v109 N/N + regressione), e i prossimi sottoprogetti (MCP import `mcp.json`, allegati).

- [ ] **Step 5: Commit**

```bash
# sparkforge
cd /home/jagones/Repositories/sparkforge && git push
# handoff
cd /home/jagones/Repositories && git add .agent/HANDOFF.md && \
  git commit -m "HANDOFF: JAG-109 skills install + slash usage"
```

---

## Self-Review

**Spec coverage:**
- §2.1 install zip → Task 1/2/5. §2.2 list/read/remove API → Task 4. §2.3 `/` injection → Task 6. §6 engine → Task 1/3. §7 API → Task 4/5. §8 sicurezza → Task 2. §9 chat `/` → Task 6 (+ Task 8 UI). §10 WebUI → Task 8. §11 errori/logging → Task 1 (errori JSON in engine/e `{error}`). §12 test S1–S10 → Task 1–6 (S1–S8, S10, S9); S10/S11 in Task 4/5. §13 gitignore → Task 7.
- Nessun requisito di spec senza task.

**Placeholder scan:** nessun "TBD/TODO/implement later"; ogni step di codice ha il codice completo.

**Type consistency:** `install_zip(data, name=None, overwrite=False)` usato identicamente in Task 1/3/5 (engine) e in `install_skill_raw(data, name=None, overwrite=False)` (Task 5). `remove(name)`/`is_local(name)` coerenti in Task 3/4. `_local_dir()` unico punto per la dir locale. `_apply_skill_slash(message)` firmato/chiamato uguale in Task 6.

**Nota di scope:** questo piano copre **solo** il sottoprogetto 1. I sottoprogetti 2 (import `mcp.json`) e 3 (allegati) avranno spec+piano propri dopo.
