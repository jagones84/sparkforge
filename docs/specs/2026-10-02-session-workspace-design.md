# Design — sessione legata a una cartella (workspace per-sessione)

Data: 2026-10-02 · Tema: JAG-115

## Problema (dal feedback utente)

JAG-114 ha aggiunto regole globali/progetto e una cartella `.sparkforge` **dentro il
progetto**, ma il workspace è **globale al server** (`~/.config/sparkforge/config.json`):
una sola cartella vale per tutte le sessioni. Un IDE reale lega **una finestra/sessione
a una cartella** ("open folder"). Domande dell'utente: «hai hardcoded i path delle rules
di progetto? come apro una nuova cartella di progetto? una sessione deve essere linkata
a un folder».

## Risposta alla domanda "path hardcoded?"

No. Il path di progetto non è hardcoded: è `<workspace>/.sparkforge/RULES.md`, con
`<workspace>` risolto a runtime. Il difetto non è l'hardcoding ma la **granularità**:
il workspace è globale invece che per-sessione.

## Progettazione

### Precedenza di risoluzione del workspace

1. `session["workspace"]` (se presente e la cartella esiste) — **vince**
2. `~/.config/sparkforge/config.json` → `workspace` (default per le nuove sessioni)
3. variabile `SPARKFORGE_WORKSPACE`
4. `REPO` (fallback)

Le sessioni senza `workspace` **ereditano dinamicamente** il default globale: nessuna
migrazione dei file sessione esistenti.

### Modulo `rules.py`

- `resolve_workspace(sess=None) -> str` (nuova): applica la precedenza sopra.
- `collect(ws=None)`, `rules_block(ws=None, max_bytes=None)`, `status(ws=None)`,
  `save(scope, content, ws=None)`: accettano un workspace esplicito.
- `get_workspace()` / `set_workspace(path)`: restano il **default globale**.
- `check_dir(path) -> str|None` (nuovo): normalizza+valida una cartella (riuso in `set_workspace`).

### server.py

- `rules_context(sess=None, ws=None)`: passa `ws` a `rules_block`.
- `_system_prompt(sess)`: `rb = rules_context(sess)` → la chat usa il workspace della sessione.
- `agent_run(..., workspace=None)` e `agent_stream_gen(..., workspace=None)`: l'agent loop
  onora lo stesso workspace (l'endpoint `/api/agent/run` lo ricava da `?session=`).
- `list_sessions()`: espone `workspace` (se la sessione ne ha uno) così la UI può mostrare il legame.

### API (api_v02)

- `GET /api/rules?session=<id>` → status del workspace risolto per quella sessione.
- `POST /api/rules {scope,content,session?}` → salva nel progetto risolto.
- `GET /api/workspace?session=<id>` → `{workspace, source, status}`.
- `POST /api/workspace {path, session?|set_default?}`:
  - con `session` → scrive `session["workspace"]` (link della sessione);
  - con `set_default` → aggiorna il default globale (`config.json`).

### WebUI (tab Rules)

- Mostra il workspace **della sessione corrente** e da dove viene (sessione/globale).
- "usa questo workspace" → applica alla **sessione corrente**; checkbox
  "imposta come default per nuove sessioni".
- Nella lista sessioni un'icona 📁 quando la sessione ha una cartella propria.

## Criteri di accettazione

- Una sessione con `workspace=A` vede le regole di `A`; una senza, quelle del default.
- `POST /api/workspace {session,path}` persiste sulla sessione, non sul globale.
- `POST /api/rules {scope,content,session}` scrive in `A/.sparkforge/RULES.md`.
- Cartelle inesistenti → rifiutate (400), nessuna scrittura.
- Nessuna regressione su JAG-114 (14/14) e sul resto.
