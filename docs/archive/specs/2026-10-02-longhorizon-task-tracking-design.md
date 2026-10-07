# Spec — Long-horizon task tracking: completion loop, unified task list, nested subagent todos, steer preemption, run metrics (2026-10-02)

Stato: **approvato** (brainstorming con l'utente). Ambito: SparkForge. ID: **JAG-129**.

## Problema (ground truth, verificato nel codice)

1. **Il gate di verifica spara una volta sola.** [server.py:2023](file:///z:/Repositories/sparkforge/server.py#L2023)
   `if not verify_nudged and tool_ctx:` → `verify_nudged` non viene mai ripristinato; dopo UN nudge
   il turno chiude comunque con todo aperti. È la causa diretta dei "pezzi di plan non fatti".
2. **`plan.incomplete` è solo un avviso** ([server.py:2122](file:///z:/Repositories/sparkforge/server.py#L2122)),
   nessuna continuazione: l'agente produce la prosa finale e **chiude** (non "chiede" di chiudere).
3. **Lo steer non interrompe.** [drain_steer](file:///z:/Repositories/sparkforge/server.py#L1883) è
   chiamato solo in cima al loop; se il turno è uscito (o è nel blocco "finale forzato") la coda non
   viene mai svuotata → messaggio perso, run non reindirizzata.
4. **Due sistemi paralleli** = confusione "todo vs plan": `taskgraph` (lista persistente per sessione)
   vs `load_plan/save_plan` legacy (`/api/plan`) vs "RUN GRAPH".
5. **Nessuna durata/working time per run** registrata.
6. **Subagent** ([subagent.py](file:///z:/Repositories/sparkforge/subagent.py)) delegano via
   `agent_run_v2` ma **senza una lista di todo propria esposta** né legame padre↔figlio (niente matrioska).

## Ricerca (pattern dominanti)

- **Ralph / Stop-hook**: all'uscita il hook verifica una condizione deterministica; se falsa **re-inietta**
  e continua, con **block cap** (Claude Code: 8 blocchi consecutivi) e **no-progress detection**.
  [teamday.ai, kuanhaohuang.com, startdebugging.net]
- **Claude `/goal`**: un modello piccolo verifica la condizione ad ogni turno → continuazione
  condition-driven. [pinggy.io]
- **Deep Agents**: `write_todos` + **subagent con lista e contesto isolati** (`task` tool). [deepwiki, pypi]
- **Ricerca (Zenith / LongHorizon-Harness)**: il fallimento è **"premature completion"**; servono
  *state preservation, gap-finding, revisable planning, independent verification, stopping discipline*
  (loop Manage-Execute-Audit). [ii.inc, arXiv 2608.01964]
- **Stop conditions**: servono terminali tipizzati (`goal`/`no_progress`/`budget`/`needs_review`),
  no-progress hashing, cap hard. [aisrc.ru, citycenterhomes.com, datasciencedojo.com]

Conclusione: **l'harness è la segretaria** — possiede la lista, la re-inietta ad ogni ciclo e non lascia
chiudere finché non è completa, con stop conditions tipizzate e cap configurabile.

## Decisioni (dall'utente)

- **Auto-continua vincolato** (ribalta la precedente scelta "solo avviso").
- **Unificare** plan/todo in UNA lista.
- **Cap di continuazione: 8 giri, editabile in config E dalla WebUI.**
- L'agente **non** deve "chiedere" di chiudere: l'harness intercetta lo stop implicito.

## Parte A — Loop di completamento (nucleo)

Dopo che il modello produce una **prosa finale** (risposta senza tool), in `chat_stream_gen`:

1. Leggi `taskgraph` della sessione. Se **non** ci sono nodi aperti → `stop_reason="goal_reached"`.
2. Altrimenti valuta le **stop conditions** (in ordine); la prima che scatta ferma il loop e pubblica
   **`plan.stopped`** `{session, reason, open, total, iterations, duration_s}`:
   - `goal_reached` — nessun nodo aperto.
   - `no_progress` — nessun cambio di stato per `no_progress_rounds` giri consecutivi, **oppure** la
     stessa `tool+args` (hash sha1) ripetuta `no_progress_rounds` volte.
   - `budget` — raggiunto `keepgoing_max` giri **oppure** `max_wall_secs` di wall-clock.
   - `blocked` — un nodo `blocked` non sbloccabile → scala all'utente.
   - `user_stop` — abort utente (flag controllato ad ogni giro).
3. Se nessuna stop condition scatta → **re-inietta** un messaggio `user` con la lista aperta
   (`taskgraph.render_todos`) + istruzione "continua: chiudi i passi aperti con evidenza oppure
   ripianifica", e **prosegui** il loop (nuova iterazione). Rimuovi il gate una-tantum
   (`verify_nudged`).
4. Ogni ciclo pubblica **`plan.continuing`** `{session, round, open, total}` per la UI.
5. Cap di sicurezza: `keepgoing_max` giri consecutivi (default 8) → stop `budget`.
6. Il controllo di "goal raggiunto" è **deterministico** (`taskgraph.all_done`); il modello veloce
   (stile `/goal`) solo come check opzionale sui casi ambigui (default off).

## Parte B — Una sola lista

- **UN concetto**: la **TASK LIST** persistente (`taskgraph`, keyed per sessione). Un **run** è solo
  *una esecuzione* della lista.
- `load_plan/save_plan` + `/api/plan`: **deprecati** → `/api/plan` diventa alias di lettura della task
  list (nessuna seconda fonte di verità).
- Prompt/agente: la lista è descritta **una volta** (usa il manifest di JAG-128A).
- UI: una sezione **TASK LIST (persistente)** + una **EXECUTION LOG (per-run)**; niente più "PLAN" e
  "RUN GRAPH" che competono.
- **Chat stile TRAE**: checklist **annidata live** (parent → subtask) dagli eventi `graph.node.*` già
  esistenti.

## Parte C — Todo annidati per subagent (matrioska)

- Ogni subagent (`subagent.spawn`) riceve il **proprio `taskgraph` keyed per `run_id`**, con le **stesse
  leggi** (status, evidenza, aperti/chiusi, stesse stop conditions della Parte A).
- Legame padre↔figlio: il nodo padre porta `child_run_id`; al termine il figlio **riassume nel padre**
  come `evidence`.
- UI: sotto-albero collassabile sotto il nodo padre.
- Ricorsione consentita ma **limitata** (`subagent.max_depth`, default 2) per evitare esplosioni.

## Parte D — Steer = preemption

- `push_steer` imposta un segnale di **prelazione**; il loop lo controlla **prima di ogni chiamata LLM e
  di ogni tool call**. Il messaggio è iniettato subito; il risultato del tool in corso è comunque
  consegnato.
- **Drain anche dopo il loop** (fase finale forzata) → se arriva uno steer lì, **apre un nuovo giro**
  invece di perdersi.
- UI: **steer = reindirizza**, **abort = ferma** (due azioni distinte). Evento `chat.steer {applied:true}`
  quando è davvero consumato.

## Parte E — Metriche per run

Per ogni run registra (in `data/runs/<id>.json` e nel `RunState`):
`started`, `ended`, `duration_s`, `iterations`, `steps`, `tokens` (prompt/completion), `model`,
`outcome` (`done`|`needs_review`|`user_abort`|`error`), `stop_reason`.
Mostrato in chat (footer + pannello) **e scritto in chiaro** a fine run.

## Config (editabile, anche da WebUI)

Nuovo blocco `runtime` in `config/tools.yaml` (sparse override in `data/tools.overlay.yaml`,
come `approvals`):

```yaml
runtime:
  keepgoing_max: 8          # giri di continuazione prima dello stop 'budget'
  no_progress_rounds: 2     # giri senza progresso prima dello stop 'no_progress'
  max_wall_secs: 3600       # tetto di tempo per run
  subagent_max_depth: 2     # profondita' massima della matrioska
```

- `GET /api/tools` include già `policy`; estendi con `runtime` (stesso meccanismo).
- `POST /api/tools` accetta `{runtime:{...}}` e li salva (merge) nell'overlay.
- **WebUI Config**: un riquadro "Runtime / long-horizon" con i campi editabili (numero giri, no-progress,
  tempo, profondità subagent), stesso pattern della card approval policy di JAG-127c.

## Test (TDD)

- `tests/v138_keepgoing_loop.py`: re-iniezione con nodi aperti; `goal_reached` quando chiusi;
  `no_progress` su stato invariato / stessa tool+args; `budget` al cap; `blocked`; `plan.stopped` e
  `plan.continuing` emessi; nessun gate una-tantum.
- `tests/v139_unified_tasklist.py`: `/api/plan` alias della task list; nessuna seconda fonte; UI ha una
  sola sezione "TASK LIST"; checklist annidata presente.
- `tests/v140_subagent_todos.py`: subagent con grafo proprio keyed per run; legame `child_run_id`;
  stesso contratto (done richiede evidenza); `max_depth` rispettato.
- `tests/v141_steer_preemption.py`: steer consumato mid-loop e dopo il loop; nessuna perdita; evento
  `chat.steer {applied:true}`; distinzione steer/abort.
- `tests/v142_run_metrics.py`: `duration_s/iterations/steps/tokens/outcome/stop_reason` registrati e
  serializzati; `runtime` GET/POST round-trip.

## Fuori scope / default

- Nessuna modifica al sandbox/approvazioni (JAG-127).
- Il verifier con modello veloce (stile `/goal`) è **opzionale, default off**.
- Rimozione fisica del codice `load_plan/save_plan` solo dopo la deprecazione (Parte B) — nessuna
  cancellazione distruttiva senza alias.
