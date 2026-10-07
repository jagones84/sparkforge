#!/usr/bin/env python3
"""v0.9.39 acceptance — difficulty / budget adattivo (JAG-134).

Compute-optimal test-time compute: la difficolta' del task scala N (best-of-N) e i
giri di continuazione (keepgoing_max). Stima deterministica dai segnali, nessuna
chiamata al modello.
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "src"))
results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


from sparkforge import difficulty  # noqa: E402
from sparkforge import bestofn  # noqa: E402

check("D1 defaults sane",
      difficulty.DEFAULTS["enabled"] is True
      and difficulty.DEFAULTS["easy_n"] == 1
      and difficulty.DEFAULTS["medium_n"] == 2
      and difficulty.DEFAULTS["hard_n"] == 3, "")

EASY = {}
MEDIUM = {"open_nodes": 3}
HARD = {"open_nodes": 4, "msg_words": 150, "prev_error": True,
        "prev_no_progress": True, "tool_count": 7, "history_fail": 3}

check("D2 banale -> punteggio 0", difficulty.score(EASY) == 0.0, str(difficulty.score(EASY)))
check("D3 massimo segnali -> punteggio capped a 1.0", difficulty.score(HARD) == 1.0, str(difficulty.score(HARD)))

check("D4 estimate easy sotto soglia", difficulty.estimate(EASY)["level"] == "easy", "")
check("D5 estimate medium alla soglia", difficulty.estimate(MEDIUM)["level"] == "medium", "")
check("D6 estimate hard alla soglia", difficulty.estimate(HARD)["level"] == "hard", "")

c = dict(difficulty.DEFAULTS)
check("D7 n_for sceglie easy/medium/hard",
      difficulty.n_for(EASY, c) == 1 and difficulty.n_for(MEDIUM, c) == 2
      and difficulty.n_for(HARD, c) == 3, "")

check("D8 rounds_for scala con la difficolta'",
      difficulty.rounds_for(8, EASY, c) == 8
      and difficulty.rounds_for(8, MEDIUM, c) == 12
      and difficulty.rounds_for(8, HARD, c) == 16, "")

check("D9 rounds_for non supera il tetto 4x",
      difficulty.rounds_for(2, HARD, c) <= 8, str(difficulty.rounds_for(2, HARD, c)))

c_on = {"enabled": True, "n": 1, "adaptive": True, "min_score": 0.0}
c_off = {"enabled": True, "n": 5, "adaptive": False, "min_score": 0.0}
check("D10 bestofn adattivo alza N sui task difficili",
      bestofn.n_of(c_on, EASY) == 1 and bestofn.n_of(c_on, HARD) == 3, "")
check("D11 bestofn non-adattivo resta al N configurato",
      bestofn.n_of(c_off, HARD) == 5, "")
check("D12 bestofn disattivato -> N=1",
      bestofn.n_of({"enabled": False, "n": 8}, HARD) == 1, "")

yaml_src = open(os.path.join(REPO, "config", "tools.yaml"), encoding="utf-8", errors="replace").read()
reg = open(os.path.join(REPO, "src", "sparkforge", "registry.py"), encoding="utf-8", errors="replace").read()
api = open(os.path.join(REPO, "api_v02.py"), encoding="utf-8", errors="replace").read()
ui = open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8", errors="replace").read()
srv = open(os.path.join(REPO, "src", "sparkforge", "server.py"), encoding="utf-8", errors="replace").read()

check("D13 config/tools.yaml ha il blocco difficulty",
      "\ndifficulty:" in yaml_src and "medium_at:" in yaml_src, "")
check("D14 registry DEFAULT_CONFIG + merge/diff includono difficulty",
      '"difficulty": {}' in reg and reg.count('"difficulty"') >= 3, "")
check("D15 API GET/POST espongono difficulty",
      '"difficulty": registry.load_config().get("difficulty")' in api
      and 'body.get("difficulty")' in api, "")
check("D16 WebUI ha la card + load/save difficulty",
      "loadDifficulty()" in ui and "saveDifficulty()" in ui and "dfHardAt" in ui, "")
check("D17 server usa difficulty per il budget dei giri",
      "_diff.rounds_for(" in srv and "_kg_override" in srv, "")

print("\n==== %d/%d checks passed ====" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
