#!/usr/bin/env python3
"""Self-evolving harness — miner di sequenze ripetute (JAG-133).

Primo stadio della sintesi autonoma di skill (Voyager-style, adattata): se
l'harness osserva che l'agente ripete la STESSA sequenza di tool su run diversi,
quella sequenza e' un candidato skill. Qui la si rileva in modo deterministico e
si emette una BOZZA di skill (proposta + `SKILL.md`), senza mai eseguire nulla e
senza auto-archiviare: la promozione resta una decisione umana (o del ciclo di
verifica sandbox, step successivo).

Modulo PURO: nessuna dipendenza dal server, testabile a unita'.
"""
import json
import os
import re
import time

REPO = os.path.dirname(os.path.abspath(__file__))

DEFAULTS = {
    "min_len": 2,      # lunghezza minima della sequenza (numero di tool)
    "min_count": 3,    # quante run diverse devono contenere la sequenza
    "max_len": 6,      # non cercare sequenze piu' lunghe di cosi'
}


def cfg(override=None):
    out = dict(DEFAULTS)
    out.update(STAGE2_DEFAULTS)
    try:
        import registry
        got = registry.load_config().get("selfevolve") or {}
        if isinstance(got, dict):
            out.update({k: v for k, v in got.items() if v is not None})
    except Exception:  # noqa: BLE001
        pass
    if isinstance(override, dict):
        out.update(override)
    return out


def _ngrams(seq, k):
    return [tuple(seq[i:i + k]) for i in range(len(seq) - k + 1)]


def mine(sequences, c=None):
    """Trova le sequenze contigue di tool ripetute su run diversi.

    Args:
        sequences: lista di run; ogni run e' la lista dei NOMI dei tool usati,
            in ordine di esecuzione.
    Returns:
        lista di {"pattern": [tool,...], "length": k, "support": n, "runs": [idx]}
        ordinata per (length*support) decrescente; i pattern piu' lunghi con lo
        stesso supporto vincono sui loro sotto-pattern.
    """
    c = c or cfg()
    mn = max(1, int(c.get("min_len") or 2))
    mc = max(2, int(c.get("min_count") or 3))
    mx = max(mn, int(c.get("max_len") or 6))
    seqs = [[str(x) for x in (s or [])] for s in (sequences or [])]
    found = {}
    for k in range(mn, mx + 1):
        for idx, s in enumerate(seqs):
            for ng in set(_ngrams(s, k)):
                e = found.setdefault(ng, set())
                e.add(idx)
    cands = [{"pattern": list(ng), "length": len(ng), "support": len(runs),
              "runs": sorted(runs)}
             for ng, runs in found.items() if len(runs) >= mc]
    # preferisci i pattern piu' lunghi: se un pattern estende un altro con lo
    # stesso insieme di run, tieni solo il piu' lungo (piu' specifico).
    cands.sort(key=lambda d: (d["length"], d["support"]), reverse=True)
    out = []
    for d in cands:
        rs = set(d["runs"])
        if any(set(o["runs"]) == rs and o["length"] > d["length"] for o in out):
            continue
        out.append(d)
    out.sort(key=lambda d: (d["length"] * d["support"], d["support"]), reverse=True)
    return out


def slug(pattern):
    """Slug filesystem-safe per un pattern di tool."""
    raw = "-".join(pattern)
    s = re.sub(r"[^a-zA-Z0-9._-]+", "-", raw).strip("-").lower()
    return (s or "skill")[:64]


def draft(pattern, support, out_dir, note=""):
    """Scrive una BOZZA di skill (proposal.json + SKILL.md). Non esegue nulla.

    Ritorna il path della cartella proposta, o None se la scrittura fallisce.
    """
    name = slug(pattern)
    d = os.path.join(out_dir, name)
    try:
        os.makedirs(d, exist_ok=True)
        proposal = {"kind": "skill", "status": "proposed", "name": name,
                    "pattern": list(pattern), "length": len(pattern),
                    "support": int(support), "created": round(time.time(), 3),
                    "note": note,
                    "next": "verify in sandbox, then archive to skills/"}
        with open(os.path.join(d, "proposal.json"), "w", encoding="utf-8") as f:
            json.dump(proposal, f, ensure_ascii=False, indent=2)
        steps = "\n".join("%d. `%s`" % (i + 1, t) for i, t in enumerate(pattern))
        md = ("# Skill proposta: %s\n\n"
              "Rilevata automaticamente su **%d run** (JAG-133). Sequenza di tool:\n\n"
              "%s\n\n"
              "## Stato\n\nBOZZA — non ancora verificata ne' archiviata. Prossimo: generare "
              "lo script, eseguirlo in sandbox sui casi reali e, se verde, promuoverla in "
              "`skills/<categoria>/<nome>/SKILL.md`.\n"
              % (name, support, steps))
        with open(os.path.join(d, "SKILL.md"), "w", encoding="utf-8") as f:
            f.write(md)
        return d
    except OSError:
        return None


def scan(sequences, out_dir, c=None, note=""):
    """Mina le sequenze e scrive una bozza per ciascun pattern. Ritorna i percorsi."""
    c = c or cfg()
    paths = []
    for cand in mine(sequences, c):
        p = draft(cand["pattern"], cand["support"], out_dir, note=note)
        if p:
            paths.append(p)
    return paths


# ------------------------------------------------------------- history -------

def _history_path():
    base = os.environ.get("SPARKFORGE_DATA_DIR") or os.path.join(REPO, "data")
    return os.path.join(base, "sequences.json")


def record(key, tools, path=None):
    """Registra la sequenza di tool di un run (per il mining successivo).

    Mantiene le ultime 500 run. Mai bloccante: un errore di scrittura e' ignorato.
    """
    seq = [str(t) for t in (tools or []) if str(t).strip()]
    if not seq or not key:
        return False
    p = path or _history_path()
    try:
        data = {}
        if os.path.exists(p):
            with open(p, encoding="utf-8") as f:
                data = json.load(f) or {}
        if not isinstance(data, dict):
            data = {}
        data[str(key)] = {"tools": seq, "ts": round(time.time(), 3)}
        if len(data) > 500:
            for k in sorted(data, key=lambda x: data[x].get("ts", 0))[:len(data) - 500]:
                data.pop(k, None)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        tmp = p + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, p)
        return True
    except OSError:
        return False


def history(path=None):
    """Le sequenze registrate, come lista di liste di tool-name."""
    p = path or _history_path()
    try:
        with open(p, encoding="utf-8") as f:
            data = json.load(f) or {}
    except (OSError, ValueError):
        return []
    if not isinstance(data, dict):
        return []
    return [e.get("tools", []) for e in data.values() if isinstance(e, dict)]


def mine_history(out_dir, c=None, path=None, note=""):
    """Mina la history registrata e scrive le bozze. Ritorna i percorsi."""
    return scan(history(path), out_dir, c, note=note)


# ------------------------------------------------- stage 2: synth/verify/archive
# Voyager-style write-gate: la skill entra in `skills/` SOLO se il check generato
# passa in sandbox. Nulla viene eseguito se non il check (self-contained), quindi
# il ciclo e' sicuro: synthesize -> verify -> archive.

STAGE2_DEFAULTS = {
    "category": "auto",     # skills/<category>/<name> in fase di promozione
    "verify_timeout": 60,   # timeout del check in sandbox
}


def _write_json(path, obj):
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=2)
        return True
    except OSError:
        return False


def _read_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _known_tools():
    """Nomi dei tool noti/abilitati ORA (per il check self-contained)."""
    try:
        import registry
        return sorted(t["name"] for t in registry.catalog() if t.get("name"))
    except Exception:  # noqa: BLE001
        return []


def _runner_src(name, steps):
    lines = [
        "#!/usr/bin/env python3",
        '"""Runner generato automaticamente (JAG-135) per la skill %s.' % name,
        "",
        "Non viene eseguito dal mining: e' il PRIMITIVO che l'harness potra'",
        "richiamare. Ogni step elenca il tool del harness da chiamare, in ordine.",
        '"""',
        "import json",
        "import sys",
        "",
        "STEPS = json.loads(%s)" % repr(json.dumps(steps)),
        "",
        "",
        "def run(invoke):",
        '    """Esegue gli step in ordine chiamando invoke(tool, args)."""',
        "    out = []",
        "    for st in STEPS:",
        '        out.append(invoke(st["tool"], st.get("args", {})))',
        "    return out",
        "",
        "",
        'if __name__ == "__main__":',
        '    print(json.dumps([s["tool"] for s in STEPS]))',
    ]
    return "\n".join(lines) + "\n"


def _check_src(name, known):
    lines = [
        "#!/usr/bin/env python3",
        '"""Check generato automaticamente (JAG-135) per la skill %s.' % name,
        "",
        "Valida skill.json: JSON ben formato, almeno uno step, ogni step con un",
        "tool noto al momento della sintesi. Verde = promuovibile. Self-contained:",
        "nessuna dipendenza dal repo, gira in qualunque sandbox.",
        '"""',
        "import json",
        "import os",
        "import sys",
        "",
        'HERE = os.path.dirname(os.path.abspath(__file__))',
        "KNOWN = set(json.loads(%s))" % repr(json.dumps(known)),
        "",
        "",
        "def main():",
        "    try:",
        '        with open(os.path.join(HERE, "skill.json"), encoding="utf-8") as f:',
        "            recipe = json.load(f)",
        "    except (OSError, ValueError) as e:",
        '        print("skill.json illeggibile: %s" % e)',
        "        return 1",
        '    steps = recipe.get("steps")',
        "    if not isinstance(steps, list) or not steps:",
        '        print("nessuno step nella recipe")',
        "        return 1",
        "    bad = [str(s.get(\"tool\")) for s in steps",
        "           if not isinstance(s, dict) or s.get(\"tool\") not in KNOWN]",
        "    if bad:",
        '        print("tool non noti: %s" % ", ".join(bad))',
        "        return 1",
        '    print("ok: %d step(s) validi" % len(steps))',
        "    return 0",
        "",
        "",
        'if __name__ == "__main__":',
        "    sys.exit(main())",
    ]
    return "\n".join(lines) + "\n"


def synth(pattern, out_dir, c=None):
    """Genera gli artefatti eseguibili per un pattern (stadio 2, codegen).

    Scrive, nella cartella della proposta, `skill.json` (pipeline dichiarativa),
    `runner.py` (primitivo invocabile) e `check.py` (verifica self-contained).
    Ritorna {"dir","skill","runner","check","steps"} o None se scrive male.
    """
    name = slug(pattern)
    d = os.path.join(out_dir, name)
    steps = [{"tool": str(t)} for t in (pattern or [])]
    recipe = {"name": name, "kind": "pipeline", "steps": steps,
              "note": "generato da selfevolve (JAG-135)"}
    try:
        os.makedirs(d, exist_ok=True)
        if not _write_json(os.path.join(d, "skill.json"), recipe):
            return None
        with open(os.path.join(d, "runner.py"), "w", encoding="utf-8") as f:
            f.write(_runner_src(name, steps))
        with open(os.path.join(d, "check.py"), "w", encoding="utf-8") as f:
            f.write(_check_src(name, _known_tools()))
        return {"dir": d, "skill": os.path.join(d, "skill.json"),
                "runner": os.path.join(d, "runner.py"),
                "check": os.path.join(d, "check.py"), "steps": len(steps)}
    except OSError:
        return None


def _run_check(proposal_dir, command, c):
    """Esegue il check nella sandbox (cwd = cartella proposta). (green, output)."""
    try:
        import sandbox
        res = sandbox.run(command, timeout=int(c.get("verify_timeout") or 60),
                          workspace=proposal_dir)
    except Exception as e:  # noqa: BLE001
        return False, "sandbox error: %s" % e
    out = (res.get("stdout") or "") + (res.get("stderr") or "")
    return res.get("exit_code") == 0, out


def verify(proposal_dir, runner=None, c=None):
    """Esegue `check.py` in sandbox e aggiorna proposal.json (verified/rejected).

    `runner(dir, command) -> (green, output)` iniettabile nei test (puro).
    Ritorna il report {"ran","green","command","duration_ms","output"}.
    """
    c = c or cfg()
    prop = _read_json(os.path.join(proposal_dir, "proposal.json")) or {}
    command = "python3 check.py"
    t0 = time.time()
    if runner is not None:
        try:
            green, out = runner(proposal_dir, command)
        except Exception as e:  # noqa: BLE001
            green, out = False, "runner error: %s" % e
    else:
        green, out = _run_check(proposal_dir, command, c)
    report = {"ran": True, "green": bool(green), "command": command,
              "duration_ms": int((time.time() - t0) * 1000),
              "output": str(out)[-1200:]}
    prop["status"] = "verified" if green else "rejected"
    prop["verify"] = report
    _write_json(os.path.join(proposal_dir, "proposal.json"), prop)
    return report


def promote(proposal_dir, skills_dir=None, c=None):
    """Archivia una proposta VERIFICATA in skills/<category>/<name>/ (write-gate).

    Rifiuta se lo status non e' `verified`. Non sovrascrive. Ritorna
    {"ok",...} oppure {"ok": False, "error": ...}.
    """
    import shutil
    c = c or cfg()
    prop_path = os.path.join(proposal_dir, "proposal.json")
    prop = _read_json(prop_path) or {}
    if prop.get("status") != "verified":
        return {"ok": False, "error": "proposta non verificata (status=%s)"
                % prop.get("status", "?")}
    name = prop.get("name") or os.path.basename(proposal_dir)
    root = skills_dir or os.path.join(REPO, "skills")
    target = os.path.join(root, str(c.get("category") or "auto"), name)
    if os.path.exists(target):
        return {"ok": False, "error": "target gia' esistente: %s" % target}
    try:
        os.makedirs(os.path.dirname(target), exist_ok=True)
        shutil.copytree(proposal_dir, target)
    except OSError as e:
        return {"ok": False, "error": "copy failed: %s" % e}
    prop["status"] = "archived"
    prop["archived_to"] = os.path.relpath(target, REPO)
    _write_json(prop_path, prop)
    _write_json(os.path.join(target, "proposal.json"), prop)
    return {"ok": True, "name": name, "path": target,
            "rel": os.path.relpath(target, REPO)}


def pipeline(pattern, out_dir, support=0, runner=None, promote_if_green=True,
             skills_dir=None, c=None):
    """Ciclo completo stadio 2: draft -> synth -> verify -> (promote se verde)."""
    c = c or cfg()
    d = draft(pattern, support, out_dir)
    if not d:
        return {"ok": False, "error": "draft failed"}
    s = synth(pattern, out_dir, c)
    if not s:
        return {"ok": False, "error": "synth failed", "dir": d}
    report = verify(d, runner=runner, c=c)
    arch = None
    if report.get("green") and promote_if_green:
        arch = promote(d, skills_dir=skills_dir, c=c)
    return {"ok": bool(report.get("green")), "dir": d, "verify": report,
            "archived": arch}

