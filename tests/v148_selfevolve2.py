#!/usr/bin/env python3
"""v0.9.40 acceptance — self-evolving stadio 2 (JAG-135).

Ciclo Voyager-style: synthesize -> verify in sandbox -> archive (solo se verde).
Il write-gate e' il cuore: una skill entra in skills/ SOLO se il check generato
passa. Qui si testa con runner iniettato (puro) e con la sandbox reale (host).
"""
import json
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


import selfevolve  # noqa: E402

check("T1 stage2 defaults sane",
      selfevolve.STAGE2_DEFAULTS["category"] == "auto"
      and selfevolve.STAGE2_DEFAULTS["verify_timeout"] == 60, "")

PAT = ["fs.read", "shell", "fs.edit"]
tmp = tempfile.mkdtemp()
d = selfevolve.draft(PAT, support=3, out_dir=tmp)
s = selfevolve.synth(PAT, tmp)
check("T2 synth scrive skill.json + runner.py + check.py",
      s is not None and all(os.path.isfile(s[k]) for k in ("skill", "runner", "check")),
      str(s))
rec = json.load(open(s["skill"], encoding="utf-8"))
check("T3 skill.json ha gli step del pattern",
      rec["kind"] == "pipeline" and [x["tool"] for x in rec["steps"]] == PAT, str(rec))

ok_src = True
for f in ("runner.py", "check.py"):
    src = open(os.path.join(d, f), encoding="utf-8").read()
    try:
        compile(src, f, "exec")
    except SyntaxError as e:
        ok_src = False
        print("   syntax: %s -> %s" % (f, e))
check("T4 sorgenti generati compilano", ok_src, "")


def green_runner(_dir, _cmd):
    return True, "ok: 3 step(s) validi"


def red_runner(_dir, _cmd):
    return False, "tool non noti: xyz"


rep = selfevolve.verify(d, runner=green_runner)
prop = json.load(open(os.path.join(d, "proposal.json"), encoding="utf-8"))
check("T5 verify verde -> status=verified",
      rep["green"] is True and prop["status"] == "verified", str(prop.get("status")))

# promote su una copia con status forzato non-verified deve rifiutare
d2 = selfevolve.draft(PAT, support=1, out_dir=tempfile.mkdtemp())
selfevolve.synth(PAT, os.path.dirname(d2))
refuse = selfevolve.promote(d2, skills_dir=tempfile.mkdtemp())
check("T6 promote rifiuta una proposta non verificata",
      refuse.get("ok") is False, str(refuse))

skills_tmp = tempfile.mkdtemp()
arch = selfevolve.promote(d, skills_dir=skills_tmp, c={"category": "auto"})
target = os.path.join(skills_tmp, "auto", selfevolve.slug(PAT))
check("T7 promote archivia in skills/<cat>/<nome>",
      arch.get("ok") is True and os.path.isdir(target)
      and os.path.isfile(os.path.join(target, "SKILL.md")), str(arch))
prop2 = json.load(open(os.path.join(d, "proposal.json"), encoding="utf-8"))
check("T8 proposal.json aggiornato a archived",
      prop2["status"] == "archived" and "archived_to" in prop2, str(prop2.get("status")))

again = selfevolve.promote(d, skills_dir=skills_tmp, c={"category": "auto"})
check("T9 promote non sovrascrive un target esistente",
      again.get("ok") is False, str(again))

# pipeline completa con runner verde -> archiviata
sk2 = tempfile.mkdtemp()
p = selfevolve.pipeline(["git", "fs.edit", "shell"], tempfile.mkdtemp(), support=2,
                        runner=green_runner, skills_dir=sk2)
check("T10 pipeline verde -> archiviata",
      p.get("ok") is True and (p.get("archived") or {}).get("ok") is True, str(p))

# pipeline con runner rosso -> NON archiviata
sk3 = tempfile.mkdtemp()
pr = selfevolve.pipeline(["web", "self"], tempfile.mkdtemp(), support=2,
                         runner=red_runner, skills_dir=sk3)
check("T11 pipeline rossa -> non archiviata",
      pr.get("ok") is False and pr.get("archived") is None
      and os.listdir(sk3) == [], str(pr))

# verify con la sandbox REALE (host): pattern valido -> verde
dr = tempfile.mkdtemp()
d_r = selfevolve.draft(PAT, support=1, out_dir=dr)
selfevolve.synth(PAT, dr)
real = selfevolve.verify(d_r)
check("T12 verify in sandbox reale: pattern valido -> verde",
      real.get("green") is True, str(real.get("output"))[:120])

# verify reale su un pattern con tool sconosciuto -> rosso (il check lo rileva)
db = tempfile.mkdtemp()
d_b = selfevolve.draft(["totally_unknown_tool_xyz"], support=1, out_dir=db)
selfevolve.synth(["totally_unknown_tool_xyz"], db)
realb = selfevolve.verify(d_b)
check("T13 verify in sandbox reale: tool sconosciuto -> rosso",
      realb.get("green") is False, str(realb.get("output"))[:120])

tools_src = open(os.path.join(REPO, "tools.py"), encoding="utf-8", errors="replace").read()
reg = open(os.path.join(REPO, "registry.py"), encoding="utf-8", errors="replace").read()
api = open(os.path.join(REPO, "api_v02.py"), encoding="utf-8", errors="replace").read()
yaml_src = open(os.path.join(REPO, "config", "tools.yaml"), encoding="utf-8", errors="replace").read()
check("T14 wiring: improve evolve/verify/promote + schema + config + API",
      'action == "evolve"' in tools_src and 'action == "promote"' in tools_src
      and '"evolve"' in reg and '"selfevolve": {}' in reg
      and "\nselfevolve:" in yaml_src
      and '"selfevolve": registry.load_config().get("selfevolve")' in api, "")
check("T15 cfg() espone i default di stadio 2",
      selfevolve.cfg().get("category") == "auto"
      and selfevolve.cfg().get("verify_timeout") == 60, "")

print("\n==== %d/%d checks passed ====" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
