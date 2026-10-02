# 2026-10-02 — Rules globali/progetto + selezione workspace (JAG-114)

## Domanda utente
"Come si modificano le rules globali e di progetto? Come si seleziona il workspace?
Si fa la cartella `.SparkForge` con le rules? Dove si salvano (cartella utente)?
Dove stanno le globali? Come fanno le altre IDE?"

## Come fanno le altre (fonti)
- **AGENTS.md** è lo standard cross-vendor (Linux Foundation / Agentic AI Foundation):
  markdown semplice, nessuno schema [agents.md](https://getknack.ai/blog/agents-md-vs-claude-md).
- Discovery **a livelli**, dal più generale al più specifico, concatenati
  root→giù; il più specifico vince:
  globale utente → repo root → sottocartella. Globali in una dotdir di `$HOME`
  (`~/.codex/AGENTS.md`, `~/.claude/CLAUDE.md`, `~/.config/opencode/AGENTS.md`).
  Cap ~32 KiB (`project_doc_max_bytes`) [qcode docs](https://docs.qcode.cc/docs/usage/agents-md).
- Claude Code: managed policy → utente `~/.claude/CLAUDE.md` → progetto `./CLAUDE.md`
  / `.claude/CLAUDE.md` → `CLAUDE.local.md`; i `.claude/rules/*.md` caricano insieme
  [mer.vin](https://mer.vin/news/claude-code-now-reads-agents-md-when-theres-no-claude-md/).

## Design SparkForge (AGENTS.md-compatibile + nativo)

Precedenza **globale → progetto** (progetto vince). Cap 32 KiB
(`SPARKFORGE_RULES_MAX`).

- **Globali (utente, tutte le sessioni)**: `~/.config/sparkforge/RULES.md` (nativo);
  se assente si usa `~/.config/sparkforge/AGENTS.md` (compatibile). Base dir
  override con `SPARKFORGE_CONFIG_DIR` (è la stessa che contiene `env`).
- **Progetto (workspace)**:
  - nativo: `<ws>/.sparkforge/RULES.md` + `<ws>/.sparkforge/rules/*.md` (ordinati);
  - se non c'è il nativo: `<ws>/AGENTS.md` (compatibile) — e viceversa.
- **Workspace**: selezionabile, salvato in `~/.config/sparkforge/config.json`
  (`{"workspace": "/path"}`), override `SPARKFORGE_WORKSPACE`, default = repo del
  harness. Il server gira sul **DGX**, quindi i percorsi sono quelli del DGX
  (`/home/jagones/...`).

### `rules.py` (motore unico)
`get_workspace`/`set_workspace`, `global_rules_path`/`project_rules_path`,
`collect()` (global+project+files), `rules_block()` (blocco per il prompt, con
cap), `save(scope, content)` (scrittura atomica), `status()`.

### `server.py`
- `RULES_POLICY` + il blocco iniettato in `_system_prompt` **e** in `agent_run`
  (chat e agent condividono le regole).
- `GET /api/rules`, `GET /api/workspace`, `POST /api/workspace`.

### `api_v02.py`
Helper testabili: `rules_status()`, `rules_save(body)`, `workspace_get()`,
`workspace_set(body)`. Route `POST /api/rules`.

### WebUI
Tab **Rules**: campo workspace + "usa", due editor (globali / progetto) con salva,
elenco dei file caricati.

## Test (TDD — `tests/v114_rules_workspace.py`)
- **R1** percorsi globali sotto `SPARKFORGE_CONFIG_DIR`.
- **R2** rules progetto da `.sparkforge/RULES.md` + `rules/*.md` (ordinati).
- **R3** fallback `AGENTS.md` (globale e progetto) quando manca il nativo.
- **R4** `rules_block` mette globali prima e progetto dopo; rispetta il cap.
- **R5** `save()` scrive atomico e `collect()` lo riflette.
- **R6** `set_workspace` persiste; le rules progetto seguono il workspace.
- **R7** niente regole → blocco vuoto, nessun crash.
- **A1** helper API presenti.

## Non-obiettivi
- Nessuna scansione di sottocartelle multiple (una sola radice per workspace).
- Nessun segreto nelle rules.
