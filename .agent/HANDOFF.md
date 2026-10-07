# SparkForge — HANDOFF (sessione autonoma notturna)

Ultimo aggiornamento: 2026-10-04 (JAG-247..256 wire/i18n/editor/registry/robustness; JAG-257 run-graph guard; JAG-258 ctx meter = stesso modello del turno; JAG-259 finestra reale dei modelli locali + ruolo subagent; JAG-260 Context sopra Plan; JAG-261 DEFAULT_BUDGET 256k; JAG-262 recovery orfani + /api/events; JAG-263 tool reconcile agent-callable; JAG-264 normalizzazione azioni near-miss; JAG-265 anti-flood CoT server+WebUI; JAG-266 regola fissa task-list + turni harness marcati; JAG-267 Context per categoria + dot-rail utente; JAG-268 update_todos mostra tutto il piano + no_progress solo su giro ozioso + regole già caricate; JAG-269 todo = oggetto per id (update_todos id-first) + reason obbligatoria su 'superseded'; JAG-270 pannello Context con % token per categoria + item apribili nell'editor + composer 13px; JAG-271 nudge con step esatti + STOP affidabile + prompt cache-safe; JAG-272 ctx breakdown che somma al totale + solo file reali apribili + inspector compatto + guard anti-LLM-stupido).
Branch: `master`. Ultimo commit: vedi sezione 1.

Questa è la memoria di lavoro. Se l'agente cade, riparti da qui. Aggiorna questo
file a fine di ogni blocco di lavoro (stato + prossimo passo + trappole).

---

## 0. CONTESTO

SparkForge = harness agentico stdlib-only (Python 3.10+), serve `webui/index.html`
(SPA), gira come servizio systemd user su DGX Spark, backend = llama.cpp router
(`:8080`). Porta HTTP `:8790`. Codice sotto `src/sparkforge/`. Test sotto `tests/`.

L'utente (Giovanni) sta **dormendo**. Istruzione: **non fermarsi**, procedere a
blocchi, verificare sempre (comando + output + numero), committare + push.

### Comandi noti (sempre via `ssh dgx "bash /path/script.sh"`, cwd `C:\Users\giova`)
- Test singolo:  `ssh dgx "python3 /home/jagones/Repositories/sparkforge/tests/<file>.py"`
- Battery:       `ssh dgx "bash /home/jagones/Repositories/sparkforge/tests/battery.sh"`
- Restart:       `ssh dgx "systemctl --user restart sparkforge.service"`
- Push:          dentro `trash/commit_<n>.sh` chiama `trash/sf_push.sh`
- URL autenticato: `http://192.168.1.37:8790/?token=<SPARKFORGE_TOKEN>`
  (token in `~/.config/sparkforge/env` sul DGX)
- WebUI live via chrome-devtools MCP (tab SparkForge).

### Regole anti-errore (imparate a caro prezzo)
- **py-spy**: non c'è sudo senza password → NON usare per dump stack del server.
- **approvals.mode = `full`** nel config attuale → l'HITL NON chiede mai; ogni
  write è auto-approvata. Per testare il gate usare `mode=normal` (solo in test
  temporanei, ripristinare).
- **Regole utente**: niente `python -c`, niente comandi inline con quote/`;`/`&&`
  via SSH → sempre script `.sh`/`.py` su file, poi `bash <file>`.
- **Sempre** strip CRLF (`sed -i "s/\r$//"`) dopo ogni upload Windows→Linux.
- Test deterministici sul DGX con `python3`; NON toccare `data/` live dai test
  (usano dir temp via `SPARKFORGE_*` env).

### Trappole già incontrate (non ripetere)
- `_router_stream` ignorava lo Stop durante silenzio del router + fallback
  non-streaming bloccante + planner non abortabile → RISOLTO (JAG-197).
- `taskgraph.reset` su task finito riusava gli id → RISOLTO (JAG-194 begin_plan).
- `_resolve_graph_node` risolveva su tutti i nodi → RISOLTO (JAG-196 plan_nodes).
- Reload interleave dei card (`after` congelato) + `node` come dict → RISOLTO
  (JAG-192).
- fs relativo risolveva su REPO invece del workspace → RISOLTO (JAG-191).
- Reply troppo spaziata (`white-space: pre-wrap`) → RISOLTO (JAG-193).

---

## 1. STATO (fatto)

- **JAG-191** fs paths bind al workspace di sessione. Commit (precedente).
- **JAG-192** reload interleave (`after` per-card, `node` stringa). Commit (prec.).
- **JAG-193** reply compatte (CSS `.bubble.md-content`). Commit `ac47756`.
- **JAG-194** nuovo task = nuovo `plan` che conserva i nodi vecchi. Commit `ac47756`.
- **JAG-195** suite `tests/v195_hard.py` + fix race `add_node` (id dentro lock).
  Commit `9a0106e`.
- **JAG-196** `update_todos`/replan/`_missing` risolvono solo sul piano corrente.
  Commit `29575a7`.
- **JAG-197** Stop reale: poll `select` sul router silenzioso + niente fallback su
  abort + planner abortabile. Commit `02d6d33`. Live: abort chiude in ~0.13s.
- **JAG-198** Ricerca skill (progressive discovery): `skills.search_skills()` +
  `skills{action:"search"}` + policy aggiornata + `tests/v198_skills_tools_awareness.py`
  (19/19). Doc ricerca `docs/research/2026-10-04-harness-frontier-and-our-niche.md`.
  README: tagline + sezione "Cosa ci distingue". Commit `71a0920`.
- **JAG-201** Due chat concorrenti sulla STESSA sessione facevano crashare il
  server: `_write_json` usava un `.tmp` fisso → `os.replace` del secondo thread
  falliva (`FileNotFoundError`) → eccezione non gestita in `do_POST` → connessione
  chiusa senza risposta → turno perso. Fix: nome temp unico per write + **lock per
  sessione** (`_turn_lock`, un turno alla volta) + reload della sessione DENTRO il
  lock (niente lost update). Test live `tests/live/v200_concurrent_chat.py` (7/7).
  Il path STREAMING aveva lo stesso lost update (append fuori dal lock nel
  request thread): ora `chat_stream_gen` fa reload+prepare+append DENTRO il lock
  del worker. Test `tests/live/v202_concurrent_stream.py` (4/4). Commit `a08857d` +
  follow-up.

- **JAG-202** Prompt budget: skills index (179) troncato 8000→2600 char + hint a
  `search`; muro tool DISABLED ~900→183 char. Prompt composto 22035→16142 char
  (~5.5k→4.0k token). Doc `docs/research/2026-10-04-system-prompt-review.md` +
  `...-harness-rdd-agenda.md`. v198 23/23.
- **JAG-203** Skill-library health audit (RDD P5): `skills.audit_skills()` +
  `skills{action:"audit"}` — READ-ONLY, find duplicates (identical descriptions),
  near-duplicate names, missing description, oversized SKILL.md. Found: 1 dup group
  (mcp-builder/mcp-server-builder-guide), 20 near pairs, 20 oversized. v198 26/26.
- **JAG-204** Verifica della memoria persistente (RDD P2, BAVAR-lite): provenance
  (`source` + `mid`), scadenza (`ttl_secs` → `expires_ts`), invalidazione
  (`memory{action:"invalidate"}` = tombstone append-only), `memory{action:"health"}`.
  Recall (`governed_query`, tool `memory`, auto-inject nel prompt) scarta record
  scaduti/invalidati salvo `include_invalid`. **Bug reale trovato e corretto**:
  `_parse_md_file` splittava su ogni `\n---\n` e SEPARAVA il front-matter dal suo
  contenuto → `ts/kind/source/mid` persi in lettura, ogni store contava come 2
  record (per questo in recall si vedeva `(None, ...)`!). Riscritto come macchina a
  stati. Nuova suite `tests/v204_memory_governance.py` (20/20, AGGIUNTA al gate).
  Schema tool `memory` aggiornato. Commit `2d7d1e1`.
- **JAG-205** Gate held-out sigillato (RDD "punto 2", fondamento di P6/P1): nuovo
  modulo `src/sparkforge/heldout.py` (dir/manifest/integrity/run/gate/pin) — store
  giudice FUORI dallo spazio agente (`SPARKFORGE_HELDOUT_DIR`, default
  `~/.sparkforge/heldout`), hash-pinnato. `selfevolve.promote` ora **fail-closed**:
  archivia solo se la suite esterna è verde (il `check.py` locale non basta più).
  Spec `docs/specs/2026-10-04-heldout-verifier-gate-design.md`, piano `docs/plans/`.
  Suite `tests/v205_heldout_gate.py` (13/13) nel gate → battery **7/7 GREEN**.
  Opt-out esplicito `SPARKFORGE_REQUIRE_HELDOUT=0` solo per dev. Commit `5d265b9`.
  *Nota:* `tests/legacy/v148_selfevolve2.py` era GIA' stale (apre `api_v02.py` nella
  root, ora in `src/sparkforge/`) — pre-esistente, non nel gate.
- **JAG-206** Step auditor read-only (RDD P1): `taskgraph` — i nodi hanno
  `requires_proof`; un nodo "rischioso" NON può chiudersi `done` con una semplice
  dichiarazione (ValueError) → serve un'evidenza **osservata** (`observed=True`).
  `audit_node()` dà il verdetto read-only, fail-safe su id ignoti. `complete_node
  (observed=True)` e `apply_write_todos` passano il flag. `tests/v206_task_auditor.py`
  (10/10). Commit `ce55746`.
- **JAG-207** Abuse/crash suite (RDD+TDD, hard): `tests/v207_abuse_hard.py` (28/28,
  con time-bound anti-hang). Ha scovato **3 bug reali**, tutti corretti:
  1. `memory._match` eseguiva `re.search` su input esterno → **DoS** da backtracking
     catastrofico (`(a+)+$`). Ora match LETTERALE + AND-di-parole, niente regex utente.
  2. `_parse_md_file` andava in crash su byte non-UTF8 in uno store corrotto →
     ora `errors="replace"`.
  3. `registry.resolve_path` sollevava su null byte (`embedded null byte`) → rifiuto
     esplicito, niente 5xx.
  Inoltre `battery.sh` ora usa `PYTHONPYCACHEPREFIX` su temp: un `__pycache__` stale
  (SMB) aveva fatto fallire v204 "per finta". Commit `9310d01`. Battery **9/9 GREEN**.
- **JAG-208** Chaos HTTP LIVE (il "far crollare il sistema"): `tests/live/v208_chaos_http.py`
  (10/10) — JSON malformato, body 2MB, path/metodo ignoti, garbage raw-socket, header
  100KB, chiusura brusca mid-request, burst 40 thread. Esito: **mai un 5xx, server in
  piedi**. Ha rivelato **2 bug reali**, corretti in `server.py`:
  1. `_body()` leggeva `Content-Length` **senza limite** (DoS di memoria) → ora cap
     `MAX_BODY_BYTES` (8MB, env `SPARKFORGE_MAX_BODY`) + drain dei byte eccedenti.
  2. un client che si disconnette mid-risposta produceva un `BrokenPipeError` **non
     gestito** → traceback nel log (0 prima → flood sotto abuso) → ora assorbito in
     `_send`. Verificato: **0 traceback** dopo il caos. Commit `ad8bcbf`.
  *Nota:* body 2MB → connessione chiusa (status 0) ma nessun traceback e server sano;
  da approfondire se serve un 413 esplicito.
- **JAG-209** "SPARKFORGE // ORBITAL COMMAND DECK" (richiesta utente: "un'app da
  fantascienza"). Nuova SPA single-file **`webui/console.html`** (~33KB): palette
  cyan/amber (no viola), starfield su `<canvas>`, pannelli **System Vitals** (4 gauge:
  MEMORY/CONTEXT/TOOLS/RUNS), **Reactor Core** (SVG rotante), **Tactical Task Graph**
  (SVG, nodi del plan), **Event Stream** (SSE `/api/feed`), **Flight Log**
  (`/api/sessions`), **Model Bay** (`/api/status.models`). Nessuna risorsa esterna/CDN,
  favoricon SVG inline data-URI. Rotta server **pubblica** `/console` (+`/console.html`,
  `/deck`) inserita **prima** del check auth in `server.py::do_GET`: la shell non ha
  segreti, i dati sotto restano auth-gated (niente token in URL solo per aprire la
  pagina). Link nel header della WebUI principale (`webui/index.html`, pulsante 🛰).
  Robustezza: guardie `state.offline` (niente overwrite del grafo DEMO dai poll),
  DEMO automatico su `file://` (CORS), empty-state overlay con `.graph-empty[hidden]
  {display:none}`, `prefers-reduced-motion`, `aria-live`, `tabindex`. Suite
  `tests/v209_console_deck.py` (18/18, AGGIUNTA al gate). Verificato in browser via
  chrome-devtools MCP: DEMO su file://, **LIVE** su `http://192.168.1.37:8790/console`
  (ONLINE, dati reali). Battery **10/10 GREEN**. Commit `32aa1e0`.
- **JAG-210** Command Deck diventa una **vera app** (non solo telemetria):
  pannello **Command Console** in `webui/console.html` — input + TRANSMIT/ABORT,
  output live che streamma la risposta dell'harness. Usa `GET /api/chat/stream`
  via `EventSource` (stessa rotta della WebUI principale): gestisce `chat.run`,
  `chat.delta` (canale `think` in corsivo, `answer` in chiaro con cursore),
  `tool.call`/`tool.result` (chip), `chat.done`, `error`, `done`. `/goal` →
  `mode=goal` (autonomo). Abort via `POST /api/chat/abort`. Tastiera: Enter=invia,
  Esc=abort. Demo `file://`/offline che "digita" la risposta (prova l'app senza
  server). Il turno è legato alla sessione selezionata; se nuova, adotta l'id che
  il server assegna. Suite `tests/v210_deck_command.py` (27/27) nel gate.
  Verifica browser (chrome-devtools): DEMO interattivo OK; pagina LIVE
  (`/console`, ONLINE, 0 errori console); contratto live provato su sessione
  usa-e-getta `zzdeckprobe` → `chat.run`+`chat.delta`+`done`, abort ok, DELETE 200.
  *Polish (notte):* la link-bar del deck ora si nasconde quando il link torna ONLINE
  (un 401 transitorio al restart la lasciava visibile); README aggiornato con la voce
  Command Deck. Verificato in browser: ONLINE + link-bar nascosta.
- **JAG-211** *Bug reale* trovato dalla battery (flake ~16% di v204, non un falso
  allarme): in `memory._parse_md_file` il front-matter passava OGNI valore per
  `_cast`, che prova `int()`/`float()`: un **`mid` esadecimale tutto-cifre**
  (es. `"33263015"`, prob. ~2.3% per record ma su più campi/record → ~16% per run)
  tornava come **int**, quindi il confronto per identità stringa
  (`x["mid"] == mid`) mancava il record → A2/B1/A5/C2 rossi a intermittenza.
  Fix: solo i campi davvero numerici (`ts`, `expires_ts`, `score`) vengono castati;
  tutto il resto resta stringa (`_cast_field`). Riprodotto con uno stress (4/25
  FAIL) e chiuso (0/25 dopo il fix). Regressione `v204` sezione E (E1 mid
  all-digit resta str, E2 session numerica resta str, E3 ts resta float) → 23/23.
- **JAG-212** Abuse round 2 (tricky, "far crollare il sistema"): `tests/v212_abuse_hard2.py`
  (19/19, deterministico, time-bounded). Attacca la *struttura* della persistenza, non
  solo il crash: contenuto memoria con una riga `---`, contenuto che IMITA il
  front-matter (`mid:`/`kind:`), 500 store + rebuild indice, 360 store concorrenti su
  12 thread, 300 nodi taskgraph + deps cicliche + label 100k, `resolve_path` con
  input ostili. Ha trovato **1 bug reale**: una riga `---` dentro il contenuto spezzava
  il record in due (l'id restava solo sul primo troncone, contenuto perso). Fix in
  `memory._render_md`/`_parse_md_file`: la riga `---` nel contenuto viene "guardata"
  con un backslash e ripristinata in lettura (contenuto preservato byte-per-byte).
  Battery **12/12 GREEN**.
- **JAG-214** Compaction + dati di contesto per-sessione (bug segnalati dall'utente:
  "non ha fatto autocompaction", "premuto compact ed ha compattato istantaneamente non
  con LLM", "passando da una sessione all'altra il ctx non cambia"). **Causa radice
  UNICA**: `context_engine.compact`, quando `len(messaggi) <= keep_recent` (es. una
  sessione con 2 messaggi, uno enorme — il "muro di x"), lasciava `old=[]` → (a) il
  summarizer LLM non veniva MAI chiamato (il compact manuale sembrava istantaneo e non
  faceva nulla), (b) lo "shrink" oltre-budget **droppava** i messaggi dall'inizio
  (perdita silenziosa). E `context_usage` misurava la dimensione POST-compressione di
  `build`, che non può mai superare la soglia → l'auto-compact non poteva scattare e due
  sessioni diverse collassavano entrambe al solo system prompt (~3625 tok identici).
  Fix:
  1. `context_engine.compact`: non tiene mai TUTTO quanto verbatim quando deve
     ridurre (lascia almeno l'ultimo messaggio); se la finestra "recente" da sola sfonda
     il budget, **riassume** i turni in eccesso invece di dropparli; un turno tenuto che
     da solo eccede il budget viene **troncato** (con testa), mai cancellato. `dropped`
     resta 0 nei casi normali.
  2. `server.context_usage`: la barra ora misura ciò che TRASPORTI (system prompt +
     transcript intero + messaggio pendente), non la build post-compressione; `pct`
     deriva da lì → l'auto-compact scatta anche senza hint del router e la barra cambia
     per sessione. Aggiunti `compacted_tokens`, `messages_after`; preferisce il conteggio
     reale del router se più alto.
  3. `server._summarize_with_llm`: cap `SUMMARIZER_MAX_CHARS` (60k) head+tail — un muro
     enorme non sfonda più la finestra del summarizer.
  4. `webui/index.html loadCtx()`: guardia contro risposte fuori ordine allo switch
     rapido di sessione; il messaggio di compact mostra il conteggio reale (`messages_after`).
  Suite `tests/v214_context_session.py` (15/15) nel gate → battery **13/13 GREEN**.
  Aggiornata l'aspettativa legacy `tests/legacy/v110` S3 (ora "shrinks to fit" invece di
  "esattamente 12": il motore riassume di più invece di droppare). **Verificato LIVE**:
  compact manuale (sessione 60k char) → `summary=llm` (modello summarizer), `dropped=0`,
  barra 19098→4159; auto su sessione 79% → `over_threshold=True`, in 8.8s riassunto LLM,
  `wall_verbatim=False`, barra 79%→1.6%. In browser la ctx bar ora differisce per sessione
  (jag99 2%, 1766eb 195%, Jago 8%).
- **JAG-215** Sweep WebUI (richiesta utente: "controlli su tutto, usa la webui").
  Endpoint sweep live 51/51, console WebUI senza errori, tutte le richieste di rete
  200. **Bug reale trovato**: il "+" del pannello Plan su una sessione SENZA grafo
  scriveva sul board legacy morto `/api/tasks` → il nodo spariva. Fix: `graph_post`
  ora CREA il grafo su azione "add" quando manca (le altre azioni restano 404);
  `addTask()` in `index.html` usa l'id SESSIONE (non `listRunId()`) e ricarica il
  plan. Suite `tests/v215_graph_ensure.py` (8/8) nel gate → battery **14/14 GREEN**.
  *Anomalia MISURATA (non ancora corretta)*: un turno "rispondi in una sola riga: ok"
  risponde in **1.4s** ma il turno resta BUSY fino a **25.9s** — ~20s di coda perché
  il planner (`start_run_graph`) gira DOPO la risposta, dentro il worker SSE. Per un
  one-liner genera comunque 2 nodi (guardia `>=4 parole`). Da valutare: non generare
   il plan per chit-chat, o renderlo non-bloccante rispetto al `done`.
- **JAG-216** *Anomalia MISURATA e corretta*: un turno one-liner rispondeva in ~1.4s
  ma il turno restava "running" per ~26s — il planner di fallback (`start_run_graph`)
  girava **sincrono** tra la risposta e `done`, dentro il worker SSE; la sessione
  restava busy e i pannelli plan/ctx si aggiornavano solo a `done`. Fix: il planner
  di fallback ora parte in un **thread daemon in background** e pubblica i nodi sul
  **feed** (`publish`), non sullo SSE del turno — la WebUI già rende i `graph.node.*`
  dal feed (handler `/api/feed` → `applyGraphEvent`, guardia di sessione). Il turno
  ora chiude appena la risposta è pronta; il grafo compare poco dopo.
  **Verificato LIVE**: turno one-liner `done` in **2.78s** (era 25.9s), grafo creato
  async a ~26s, `graph.node.added` assente dallo SSE del turno. Battery **14/14 GREEN**.
  Nuovo test live `tests/live/v216_planner_async.py` (5/5, server richiesto).
  *Residuo noto*: il planner impiega ~20-47s (modello 27B "thinking", non-blocking ora).
- **JAG-217** *Bug reale (il "hang" segnalato dall'utente)*: la WebUI sceglie il modello
  da `localStorage["sf_model"]` (o dal modello della sessione). Sul browser dell'utente
  era `win:nex-n2.5-mini-uncensored-iq4xs` (provider `win:` = PC Windows via Tailscale,
  `100.76.251.9:8080`). Quando quel PC è spento, `urlopen` resta BLOCCATO sul connect
  del sistema operativo fino a **~140s** prima che parta il fallback → il turno sembrava
  appeso. Meccanismo: i MIEI test server-side NON passavano `&model=…`, quindi usavano
  il default locale (qwen) → veloci; la WebUI passava `win:` → hang. **Fix**: `_reachable()`
  (probe TCP, `SPARKFORGE_CONNECT_TIMEOUT` default 3s) chiamata all'inizio di
  `_router_stream`, che solleva subito se l'endpoint è irraggiungibile → failover
  quasi istantaneo. `tests/v217_provider_failfast.py` (7/7, deterministico, socket stubbato)
  nel gate → battery **15/15 GREEN**. Verificato: repro `win:` ora 1.6s (PC acceso);
  con host offline il turno fallisce in <1s e passa al modello successivo.
- **JAG-218** Richieste utente sulla WebUI:
  1. **Indicatore RUNNING per-sessione**: era un punto verde pulsante → ora un **anello
     circolare rotante** (`sfspin`) sulla riga della sessione mentre il turno gira.
  2. **Notifica "lavoro finito" mentre sei su un'altra sessione** (NON esisteva): nuova
     classe `.sess.done` con **🔔**, un **toast** cliccabile in basso a destra e il
     **titolo del tab** che mostra `(N) 🔔`. Si pulisce all'apertura della sessione
     (`clearDone` in `selectSession`). Persiste i marker in `doneSessions` (sopravvive
     al re-render di `loadSessions`).
  3. **UI SOLO in inglese**: tradotte TUTTE le stringhe utente residue in
     `webui/index.html` (~40) e `webui/assets/editor.js` (~16) (`console.html` era già EN).
     Verificato: 0 errori console, grep italiano = 0, feature verificate via computed
     style (`::before` animation `sfspin`, content `🔔`, toast, titolo).
  **Verificato in browser**: reload senza errori; `setRunning`→`sfspin`; `markDone`→🔔+
  toast+titolo; `clearDone`→pulito.
- **JAG-219** Sweep V&V sistematico della WebUI (richiesta utente, "fino allo sfinimento").
  Metodo: navigazione live + chrome-devtools (console, network, computed style, DOM).
  Esito prima passata (nessun bug nuovo trovato oltre a 215/217):
  * **112 richieste HTTP → tutte 200** (nessun 4xx/5xx).
  * **Console 0 errori/0 warning** dopo reload e dopo un turno reale.
  * **7/7 pannelli rail** (Plan, Context, Approvals, Files, Browser, Terminal, Feed)
    si aprono con contenuto.
  * **Impostazioni**: tutte le sezioni presenti e **in inglese** (0 stringhe IT).
  * **Flusso end-to-end**: nuova sessione → invio col modello della WebUI
    (`win:nex-n2.5-mini-uncensored-iq4xs`) → risposta `"ciao"` (`model` corretto, nessun
    errore) → riga `running` con anello `sfspin` → switch → 🔔 + toast + titolo `(1) 🔔`.
  * Sessioni di test create dallo sweep **cancellate** (repo/pannello puliti).
  * Restano da coprire (prossime passate): steer durante un turno, abort su turno con
     tool, DELETE sessione mentre gira, palette comandi, fidelity del reload, deck `/console`.
- **JAG-219b** *Bug UX*: il blocco chain-of-thought (CoT) appariva a volte SOPRA e a
  volte SOTTO la risposta, perché veniva inserito nel DOM al primo delta del canale
  `think`. Se il modello streamma `reasoning_content` prima → CoT sopra; se la risposta
  arriva prima → CoT sotto. Fix in `webui/index.html::ensureThink`: se esiste già una
  risposta, il CoT viene inserito **prima** di essa → posizione stabile (sempre sopra).
  Verificato in browser (ordine DOM + log invariato).
- **JAG-220** Studio dell'architettura dei **system prompt** (richiesta utente) +
  regola "programmare in inglese". Creato `.agent/README-system-prompts.md`: il prompt
  è una **lista ordinata di 12 sezioni** (`prompt.SECTIONS`), alcune **statiche**
  (testo in codice: `SYSTEM_PROMPT`, `RULES_POLICY`, `SKILLS_POLICY`, `MEMORY_POLICY`,
  `CAPABILITY_RULE`) e altre **dinamiche** (tools, skills, rules, memory, state,
  self-summary). Overlay file ADDITIVI in `~/.config/sparkforge/prompt.d/` (globale) e
  `<ws>/.sparkforge/prompt.d/` (progetto), precedenza PROGETTO > GLOBALE > DEFAULT.
  Chiarito che i tre "hardcoded" segnalati NON lo sono: la lista skill è l'indice LIVE
  di `skills/` (179), la TASK LIST è il taskgraph della sessione (`context_summary`),
  i tool `pmcp__*` riflettono i client MCP connessi. Regola "codice/commenti/log/UI in
  INGLESE" aggiunta a: regola globale live (`~/.trae/user_rules/rule-1771063330286.md`),
  doc globale (`user_rules - GENERAL.md`) e `.trae/rules/project_rules.md`.
- **JAG-221** V&V "stramba" (2ª passata): integrità DOM (0 id duplicati), input vuoto
  non apre stream, escaping reply via **DOMPurify** confermato (`onerror`/`javascript:`/
  `<script>` rimossi → nessun XSS), toggle rapidi dei pannelli OK. Due falsi allarmi
  spiegati: la rail mostrava **1 sola sessione** per DOM **stale** (i miei DELETE via API
  non richiamavano `loadSessions`; le sessioni extra erano già rimosse nel batch di ieri);
  e un **401** in console era il **mio test** `<img src=x>` che caricava `/x`.
- **JAG-222** *Bug reale (data-loss/resurrezione)*: cancellare una sessione **mentre
  il suo turno girava** NON abortiva il turno, e il worker — al termine — riscriveva
  il transcript (**resurrezione**: misurato live, il file ricompariva con la risposta
  completa). Fix in `server.py`:
  1. `DELETE /api/sessions/<id>` ora fa `push_abort(sid)` **e** mette l'id in un
     **tombstone** (`_DELETED_SESSIONS`) prima di purgare i file;
  2. `save_session` **salta la scrittura** se l'id è tombstoned (nessuna resurrezione);
  3. `get_or_create_session` **cancella** il tombstone su una (ri)creazione esplicita.
  Test `tests/v222_delete_running.py` (8/8, deterministico) nel gate → battery
  **16/16 GREEN**. **Verificato LIVE**: turno abortito in **0.5s**, sessione
  `session not found` (non ricreata), file assente su disco. Sweep: steer ok
  (`queued:1`), abort ok (0.4s), re-attach dopo reload mid-turn ok, palette ok
   (19 voci, Ctrl+K), deck `/console` ONLINE con 0 errori console.
- **JAG-223** *Bug reale (HTML injection)*: il titolo di sessione era inserito nella
  rail via `innerHTML` **senza escaping** → un titolo `<img src=x onerror=alert(1)>`
  veniva **eseguito** (confermato in browser: `<img>` creato). Fix in `webui/index.html`:
  `esc()` sul titolo nella rail (e sul `label` della lista slash `/`), e `esc()` esteso
  a `> " '` (prima solo `& <`) così copre anche gli attributi (`title=` del workspace).
   Verificato: nessun `<img>`, titolo reso letterale (`&lt;img…&gt;`).
- **JAG-224** *Anomalia telemetria (domanda utente sul deck)*: nel Command Deck la
  chip **TASKS** mostrava `173 open / 173` — veniva da `/api/status.tasks` = il **board
  legacy morto** `data/tasks.json` (173 task `todo` accumulate; l'harness non lo usa più
  dalla JAG-63), e **contraddiceva** il pannello Plan della main chat per la stessa
  sessione. Fix in `webui/console.html`: la chip TASKS ora usa il **grafo della sessione
  attiva** (`state.graph`), con fallback al board solo in demo/offline. Verificato nel
  deck: ora `TASKS 3 open / 7` (= grafo di `Jago_session`). Nota: la **Model Bay** mostra
  il roster del router (7 alias, `n_ctx 256k` = *finestra di contesto*, barra =
  loaded/unloaded) — NON l'uso del contesto; l'uso reale è la gauge CONTEXT (9%, sessione
  attiva). FLIGHT LOG legge `/api/sessions` come la main chat (stesse sessioni).
- **V&V pass 2 (r4) — flussi residui via WebUI** (chrome-devtools, sessione `Jago_session`/router
  DGX). Tutti verificati live, nessun nuovo difetto:
  - **Model switch**: `chooseModel()` persiste per-sessione (localStorage `sf_model` + `POST
    /api/sessions/<id>/model`) e `currentModel()` lo riflette; isolamento per-sessione e
    ripristino OK. Il default globale era `win:nex-n2.5-mini-uncensored-iq4xs` (provider Windows
    Tailscale, `avail:true` al momento) — scelta valida, non un bug; il default di config è
    `dgx:qwen-3.8-27b-uncensored-q8`.
  - **Workspace picker** (`/api/fs/dirs`): root `/home/jagones`, navigazione, "up", chiusura OK.
    Nota: `/home/jagones` contiene davvero spazzatura (` \`, `"`, `${CCCC_HOME}`, `@`, `;`, `%sn`)
    da vecchi script shell senza quoting — non è un bug dell'app.
  - **MCP reload** (`POST /api/mcp/reload`): 2 client (`pmcp`, `filesystem`).
  - **/goal mode**: turno `mode=goal` completato in 6.5s, sessione temporanea creata e cancellata
    senza residui.
  - **Approval gate** (`GET /api/approvals?status=pending`): backend OK (pending 0; stats total
    500 / auto_approved 499). End-to-end con tool gated (mode=normal) non eseguito.
  - **Editor** (`/api/fs/read`): `README.md` (33485 byte) caricato e renderizzato
    (marked+DOMPurify), 1 tab, chiusura OK.
  - **Diff** (`GET /api/edits/diff`): la vista apre e gestisce il caso "no edits"; un diff reale
    con righe non è stato esercitato (serve un edit journaled).
  - **Console**: deck `/console` 0 errori; main chat 1 solo 404 transitorio (`/api/history` su
    sessione cancellata). Guard JAG-189 verificato: una sessione inesistente viene scartata
    subito (`sessionId → null`), nessun 404 ripetuto.
- **JAG-225** *Processo runaway (100% CPU) — root cause + garanzia*: trovato `python3
  trash/diag_ctx.py` (PID 2805593) che girava a vuoto al 93.9% CPU da 1h22m, `wchan=0`,
  orfano (PPID 1). **Non è un bug del codice attuale**: la timeline lo prova — il processo
  è partito ~10:10, mentre `context_engine.py` è stato modificato alle 10:15 e `server.py`
  alle 11:17, quindi girava una **snapshot di codice vecchia in memoria** (mai ucciso). Sul
  codice attuale NON è riproducibile: `diag_ctx.py` completa in **0.32s**, i 7 test legacy di
  compaction passano, `pgrep diag_ctx` pulito. Ucciso con `kill 2805593` (core liberato).
  Prevenzione: nuovo **`tests/v225_compact_bounded.py`** (input adversariali: 1M-char singolo,
  5000 messaggi, 300×50k, budget=1, summarizer che fallisce, keep_recent=0) che blocca la
  garanzia "compaction termina sempre <3s" — aggiunto alla battery (**17/17 GREEN**). Il loop
  di shrink è comunque già limitato (`guard < 4096`).
- **JAG-226** *XSS reale nella WebUI (verificato in browser)*: `toolCard()` interpolava il
  **nome del tool** (`data-tool="${name}"`, `${name}`) e gli handler `agent.thought`/`tool.call`
  interpolavano `d.action`/`d.thought`/`d.tool` in `innerHTML` **senza escaping**. Payload
  provato: `evil"><img src=x onerror="window.__pwn=1">` → in-browser `window.__pwn=1` e 2
  `<img>` iniettati in `#log` (**esecuzione JS arbitraria**). Fix in `webui/index.html`:
  `esc()` su `toolCard` (attributo + testo), `agent.thought`, `tool.call`, `showNodeDetail`
  (evidence) e sul toast "finished". Ri-probe: `imgsAdded=0, pwnTool=0, pwnThought=0`.
  Regressione: **`tests/v226_webui_escaping.py`** (9/9, static guard). Le risposte assistant
  erano già sanificate (`mdToHtml` → DOMPurify).
- **JAG-227** *UI: pulizia log + deck*: (a) rimosso il bottone "minimize" **morto** dalle Settings
  (`#swMin`, senza handler) — resta solo la ✕; (b) i blocchi chain-of-thought non restano più
  vuoti/"live": su ogni nuovo blocco e a fine turno `_tidyThink()` elimina i CoT vuoti e toglie il
  suffisso "(live)…" (era il "disordine: sezioni done senza risposta, solo pensiero"); (c) deck:
  la **Model Bay non disegna più una barra piena al 100%** per il modello loaded (sembrava "contesto
  saturo") — ora mostra `window 256k` + `loaded/unloaded`. **Contesto**: verificato che deck e main
  chat usano lo **stesso** `/api/context`; per `VV_g5_coding` il conto è `source:"model"`,
  `tokens_used=19139` (sysp 4243 + transcript 13678, preferendo i `prompt_tokens` reali del router),
  `7%` di 258k → **coerente**.
- **g5 — test task complesso (fatto)**: `/goal` su `/home/jagones/Repositories/vv_test_project`
  (session `48c6e90156c5`, model `win:…`). Il harness ha **guidato** il modello: nudge dopo ogni
  step, enforce "un solo doing", **evidence obbligatoria** per il done, **path-guard** (fs.read fuori
  dai root rifiutato), **uso skill** (il modello ha fatto `skills search` + `skills read tdd`),
  offload output grandi, retry su JSON malformato. Esito: `plan.stopped reason=goal_reached
  open=0/8`, file `todo.py`+`tests/test_todo.py`+`README.md` e **`7 passed`, pytest rc 0**.
  Nota: il mini-model remoto è lento (~6 min) e ha emesso JSON invalido 2 volte (recuperato).
- **JAG-228** *Hardening UI (bug hunt)*: le funzioni di rendering non lanciano più su voci `null`
  negli array dati dal server — fixate `showNodeDetail` (evidence), `hitlCard` (open),
  `renderProviders` (providers/models), `_editLine`/`editsChip` (files). Smoke in browser con input
  anomali → **0 errori**; console pulita su reload + switch sessioni + apertura pannelli. Resta da
  guardare `taskTree(null)` → **fatto in JAG-229** (`.filter(Boolean)`).

- **JAG-229** *Robustezza input (bug hunt, verificato LIVE)*: due classi di bug.
  (a) **Server**: `int(qs.get("since", 0))` & simili (`/api/feed`, `/api/runs?limit=`,
  `/api/agent/run?max_steps=`) lanciavano `ValueError` NON gestita → la connessione
  veniva RESETTATA invece di dare una risposta pulita; idem `Content-Length` malformato
  in `_body`/voice/zip. Aggiunti `_int_arg(qs,key,default)` + `Handler._content_length()`
  (fallback sicuro su qualsiasi valore malformato). Riproduzione: `/api/feed?since=abc`.
  (b) **WebUI**: ogni input numerico delle Settings usava `+$("id").value` → svuotare il
  campo dava `+""==0` e digitare junk dava `NaN` (poi serializzato a `null`): config
  corrotta silenziosamente. Aggiunto `numField(id, fallback)` e migrati TUTTI i save
  (runtime/verifier/best-of-N/difficulty/selfevolve). Verificato in browser: `vfTimeout="abc"`
  → salvato `120` (non 0/NaN). Test: `tests/v229_robustness.py` (26/26), live C11 in v208.

- **JAG-230** *Path traversal via session id (SICUREZZA, verificato LIVE)*: l'id sessione
  arriva verbatim dal client e finiva in `os.path.join(SESSIONS_DIR, sid + ".json")` in
  `load_session`/`save_session`/`_purge_session_artifacts` (il DELETE aveva già una guardia,
  gli altri no). Un `session=../../x` permetteva **lettura** di un `.json` arbitrario,
  **scrittura** (sovrascrittura) di un `.json` fuori dallo store, e (via purge) **unlink**
  arbitrario. Aggiunto `_valid_sid()` (token semplice: `[A-Za-z0-9_.-]{1,120}`, no `..`,
  tipo string) applicato a `load_session` (→None), `save_session` (→no-op),
  `_purge_session_artifacts` (→[]), `get_or_create_session` (id non valido → nuovo id sicuro)
  e `do_DELETE` (riusa la stessa guardia). Test: `tests/v230_sid_traversal.py` (25/25),
  live C12 in v208 (`?session=../../etc/passwd` → 404, nessun leak).

- **JAG-231** *Wire-type robustness (bug hunt, verificato LIVE)*: tre bug della stessa
  famiglia (dati non fidati dal client).
  (a) **Body JSON non-oggetto**: `POST` con `[1,2]`, `"x"`, `42`, `true`, `null` è JSON
  valido ma non un dict → ogni handler fa `body.get(...)` → `AttributeError` →
  connessione DROPPATA senza risposta. `_body()` ora torna `{}` se `parsed` non è un dict.
  (b) **int non protetti**: 13 punti in `api_v02.py` (`?limit=abc`, `?since=abc`,
  `{"max_steps":"abc"}` …) + `server.py` `/api/agent/run`·`/api/eval/run` + `acp.py`
  + `subagent.py` → `ValueError` non gestita → reset. Aggiunti `_int()` (api_v02),
  `_as_int()` (server), try/except (acp, subagent). `providers._to_int()` per
  `context_length` (es. `128k` faceva crashare `/api/models`).
  (c) **improve._path(pid)**: `pid + ".json"` con pid non-stringa (`POST /api/improve
  {id:123}`) → `TypeError` → reset; inoltre pid traversal → escape dallo store. Ora
  rifiuta tutto ciò che non è un token semplice.
  Test: `tests/v231_body_and_ids.py` (21/21), live C13 in v208.

- **JAG-232** *Stored XSS via SVG inline preview (SICUREZZA, verificato in browser)*:
  `/api/fs/raw` serviva qualunque `image/*` — incluso `image/svg+xml`. Aperto come
  documento top-level sull'origine dell'harness l'SVG esegue il suo JS (PROVATO in
  browser reale: `<svg onload>` ha settato un globale, `document.contentType ===
  image/svg+xml`). Il workspace è scrivibile dall'agente → un `.svg` piantato era
  ruba-token (il token sta in localStorage). Fix: `_fs_raw` ora usa una ALLOW-LIST di
  tipi inerti (raster + PDF), niente `startswith("image/")`; aggiunto
  `X-Content-Type-Options: nosniff` a tutte le risposte. Test: `tests/v232_svg_preview.py`
  (8/8), live C14 in v208 (svg → 415, png → 200).

- **JAG-233** *Crash wire → connessione DROPPATA (bug hunt sistematico, verificato LIVE)*:
  una surface-fuzz (query malformate + body type-confused su ~1100 richieste) ha trovato
  route che **chiudevano il socket senza risposta** (eccezione non gestita → "Exception
  occurred during processing of request" nel journal). Causa sistemica: `Handler._send(code,
  None)` cadeva nel ramo `else: obj.encode()` → `AttributeError: NoneType.encode`.
  Qualsiasi route che ritorna `None` droppava, es. `GET /api/subagent?id=<ignoto>`.
  Fix: `_send` serializza in JSON tutto ciò che non è `bytes`/`str` (None/int/bool/dict/list);
  `/api/subagent` con id ignoto ora → **404**. Test `tests/v233_wire_crashes.py` (28/28).
- **JAG-234** *`POST /api/meta` droppava SEMPRE* (anche con body vuoto): `meta.candidate_label`
  faceva `cand.get("model","default")[:20]` — `.get` ritorna il valore anche se è `None`
  (la candidate space può lasciare il campo vuoto) → `None[:20]` TypeError; idem `%d` con
  una stringa. Fix: ogni campo coercito a scalare sicuro. Test in v233.
- **JAG-235** *`POST /api/agent/control` droppava* con `{"run_id":[1]}`: `RUNS.get([1])` →
  `TypeError: unhashable type: 'list'`. Fix: `run_get` rifiuta gli id non-stringa. Test in v233.
- **JAG-236** *`POST /api/acp/connect` droppava* con `{"url":999}`: `ACPClient.__init__`
  faceva `url.rstrip("/")` su un int → `AttributeError`. Fix: `connect()` valida name/url
  (stringhe non vuote) + `__init__` coerce url/token. Test in v233.
- **JAG-237** *`mcp_client.disconnect_all` non thread-safe*: iterava `self.sessions.values()`
  SENZA il lock mentre `start_all` (altro thread) vi inseriva → "dictionary changed size
  during iteration" (`POST /api/mcp/reload` in gara con uno start). Fix: snapshot + clear
  sotto `self._lock`, chiusura delle sessioni fuori dal lock. Test in v233.
- **JAG-238** *Contesto "195%" fantasma + `/api/context` che droppa* (segnalato dall'utente).
  Diagnosi in WebUI + API: le sessioni a 195% erano **junk dei MIEI test** (messaggio singolo
  da 2.000.000 char `"x"*2M` inviato a `/api/chat` dal caos v208 → ~504k token). Inoltre
  `probe231` (creata da un test) aveva un **content non-stringa** (un client aveva POSTato
  `{"message": 123}` e l'int veniva persistito) → `context_engine.count_tokens` faceva
  `len(int)` → `/api/context` **droppava**; `loadCtx` ingoiava l'errore e lasciava a schermo
  il **% della sessione precedente** → "anche una sessione piccola sembra al 195%".
  Fix: (a) `count_tokens` coerce a str; (b) `compact`/`_summarize_with_llm` coerce content;
  (c) `/api/chat` rifiuta `message` non-stringa (400) e `append_message` coerce (choke-point);
  (d) `loadCtx` in caso di errore fa `ctxNa("n/d")` (niente % stantio). Test
  `tests/v238_context_robustness.py` (14/14). **Verificato LIVE**: `/api/context?session=probe231`
  → 200; `POST /api/chat {message:123}` → 400; in browser lo switch sessione aggiorna la barra
  (VV_g5_coding 7% · 18k tok, Jago_session 9% · 22k tok).
  **RISPOSTA a "le sessioni condividono il contesto?"**: NO. Ogni sessione ha il suo
  transcript; `/api/context?session=<id>` dà valori diversi per sessione (verificato). Il
  modello locale (llama.cpp) è **stateless per richiesta**: il KV-cache vive in uno slot e
  NON è condiviso tra sessioni logiche; l'harness ricostruisce il prompt da zero ad ogni
  turno. Stesso discorso per i cloud LLM (API stateless: si rimanda tutta la history).
  **Autocompaction**: `prepare_session_for_turn` scatta a `pct ≥ 75%` (target 60%) MA solo
  **all'inizio di un turno** (non "a riposo") e **non può ridurre un singolo messaggio
  gigante**: `compact` riassume i turni VECCHI e tiene il più recente (troncato se sfonda).
  Quindi una sessione con UN solo messaggio enorme resta >100% nella barra (che mostra ciò che
  *trasporti*, JAG-214) finché non la si invia — e allora `build` tronca il prompt per farlo
  stare. Allineato al mondo: Claude Code auto-compatta a ~95%, Anthropic ha compaction
  server-side; noi a 75% client-side.
- **JAG-239** *Igiene dei test live (causa del junk)*: `tests/live/v208_chaos_http.py` C3
  inviava 2MB a `/api/chat` → creava una sessione REALE (e chiamava il modello). Ora C3 usa
  `POST /api/context/preview` (processa senza persistere). **Pulizia**: cancellate via
  `DELETE /api/sessions/<id>` le sessioni junk (5×"session xxxxx" 2M, `probe231`,
  `jag99-autocompact-accept`); restano solo le reali (`VV_g5_coding`, `Jago_session`).
  Guardia statica in v238. v208 ora **22/22** (aggiunte C15: i payload JAG-233..236 non
  droppano più) e non lascia sessioni.

- **JAG-240** *UI: il chain-of-thought finiva DOPO la risposta* (segnalato dall'utente:
  "vedo il pensiero finale dopo il messaggio, il pensiero va PRIMA della risposta").
  Causa: lo stream LIVE mette la CoT SOPRA (`ensureThink` → `insertBefore(curAns)`), ma
  `loadHistory` — che gira a **ogni `done`** — la appendeva SOTTO (`d.appendChild(det)`).
  Quindi ogni turno, appena finito, si "ribaltava" con il pensiero in fondo. Fix: la
  history renderizza la CoT come blocco proprio (`<div class="msg ai">` con who+details)
  **inserito prima** della risposta. **Verificato in browser**: la sequenza finale ora è
  `… THINK#We need need answer pl | ANSWER#Built the stdlib-only …` (CoT sopra). Test v240.
- **JAG-241** *CLI `models ls` non stampava NULLA*: leggeva `out["models"]` da `/api/models`,
  che ritorna `{providers, router_models}` (nessuna chiave top-level `models`). Ora stampa
  il **roster del router locale** (alias · LOADED/unloaded · Nk ctx) + i provider e i loro
  modelli. Verificato LIVE: 7 modelli + provider `dgx`. Test v240.
- **JAG-242** *Stringhe UI in ITALIANO* (viola la regola "UI/codice in inglese"):
  `context_display` (fonte unica per WebUI + Android + CLI) ritornava `"nessuna sessione"`,
  `"usati … token"`, `"· sopra soglia"`, `"auto-compact al …"`, `"contesto n/d"`. Tutte
  tradotte in inglese (`no session`, `used … tokens`, `over threshold`, `auto-compact at`,
  `context n/d`). Verificato LIVE via `forge context show`. Test v240.
- **JAG-243** *CLI `chat --stream`: `[90m…think[0m` letterale* (ANSI senza byte ESC). Ora
  `\x1b[90m…\x1b[0m`. Test v240.
- **JAG-244** *CLI `plan` non poteva puntare a una sessione*: il plan è PER-SESSIONE
  (task graph), ma `plan show/toggle/set` non passavano `session` → prendevano il default
  vuoto (`GOAL: (none)`). Aggiunto `--session ID` (query per `show`, body per `toggle`/`set`).
  Verificato LIVE: `plan show --session 48c6e90156c5` → gli 8 nodi. Test v240.
- **JAG-245** *Docs CLI ufficiale aggiornata*: `docs/CLI.md` ora documenta `plan … [--session ID]`,
  la distinzione **plan per-sessione vs `tasks` (board legacy `/api/tasks`)**, e la forma
  dell'output di `models ls`. README già linka `docs/CLI.md`.
  Test `tests/v240_ui_cli.py` (13/13) nel gate → battery **25/25 GREEN**.
- **JAG-246** *CLI crash su argomenti con spazi/caratteri URL*: `memory search "porta staging"`,
  `blackboard search "hello world"` (e ogni query con spazio/`&`) facevano **eccezione non
  gestita** (`urllib` → `InvalidURL`) → traceback e exit 1. Fix: helper `_q()` che URL-encoda
  OGNI valore di query (chat/agent stream, memory, blackboard, subagent, context, plan,
  sessions history) + `req()` ora cattura qualunque eccezione client e ritorna `{"error": …}`.
  Verificato LIVE: `rc=0`, niente traceback. Test v240 esteso (19/19).
- **JAG-247..250** *Wire type-confusion su providers/rules/workspace* (caccia bug
  dopo JAG-246): input JSON/query non-stringa raggiungeva `.strip()`/`int()`/`dict()`
  → eccezione → **connessione DROPPATA** (nessuna risposta). Fix:
  - **JAG-247** `providers.upsert_provider`: `id` deve essere `str` (`_validate_provider`),
    niente `.strip()` su int/lista/dict; `kind`/`base_url`/`api_key_env` validati.
  - **JAG-248** `providers.add_model`/`remove_model`/`set_default`: coercizione del
    valore wire; `context_length` non numerico → `{"ok": false, "context_length must be an integer"}`.
  - **JAG-249** `rules._win_to_posix`/`set_workspace`: coercizione del path; messaggi in inglese.
  - **JAG-250** `providers.upsert_provider`: `models:[1,2]` faceva `dict(1)` (TypeError)
    → normalizzato a lista di oggetti, `models` non-lista → errore pulito.
  - i18n: rimaste le ultime stringhe ITALIANE user-facing (`cartella inesistente`,
    `sessione inesistente`) anche in `server.py` `/api/sessions/new` → ora inglese.
  Verificato: 14 probe live `/api/{providers,providers/models,providers/default,workspace,
  sessions/new}` → **0 DROP**; overlay `providers.local.yaml` salvato/ripristinato dai probe.
  Nuova suite `tests/v247_api_types.py` (35/35) → battery **26/26 GREEN**.
- **JAG-251** *Wire type-confusion su `/api/tools` (settings) + `rules.save`*: ogni campo
  numerico del Config panel (`runtime.*`, `verifier.timeout_secs`, `bestofn.n`/`min_score`,
  `difficulty.*`, `selfevolve.*`) era convertito con `int()`/`float()`/`list()` NON protetti:
  un valore non numerico (es. `{"runtime":{"keepgoing_max":"abc"}}`) sollevava e la connessione
  veniva **DROPPATA**. `rules.save` scriveva `content` (wire) direttamente su disco e faceva
  `len(content)`. Fix: `update_policy` ora delega a `_update_policy` con try/except
  `(TypeError, ValueError)` → `{"ok": false, "error": "invalid settings value: …"}`;
  `rules.save` coerce `content` a stringa (write + `chars`). i18n: ultime stringhe IT
  user-facing (`scope deve essere…`, `path richiesto…`, `proposta non verificata`,
  `generato da selfevolve`, `pattern di tool ripetuto…`, marker `[troncate]`) → inglese.
  Verificato: 12 probe live `/api/tools` + `/api/rules` → **0 DROP**; `tests/v251_settings_wire.py`
  (22/22) → battery **27/27 GREEN**.
  *(Debito noto: restano docstring/commenti in italiano in alcuni moduli — bestofn, difficulty,
   verify, heldout, selfevolve, tools — da tradurre in un passaggio dedicato.)*
- **JAG-252** *Editor WebUI*: (a) chiudendo l'ULTIMO file aperto il tab set NON veniva
  persistito → il file (es. `RULES.md`) riappariva alla riapertura del dock; ora
  `closeTab` salva il set vuoto prima di nascondere. (b) aggiunto lo **splitter
  ridimensionabile** tra l'albero file e l'editor (drag, width memorizzata in
  `sf_ed_tree_w`, si nasconde con l'albero). Verificato nel browser (chrome-devtools):
  `rawAfter={"paths":[],"active":-1}`, `reappearedAfterRestore=false`; albero 210→359px
  persistito. `webui/assets/editor.js` servito con `Cache-Control: no-store`.
- **JAG-253** *`/api/status` (e `/api/tools`) DROPPAVANO la connessione*: `registry.catalog()`
  chiamava `tool_names()` e poi `tool_spec(name)` per ogni nome, e ognuno **rivalutava**
  `_external_tools()`. Quando un server MCP stava riconnettendosi le due viste divergevano:
  un nome era elencato ma `tool_spec` ritornava `None` → `None["enabled"]` → TypeError →
  socket chiuso senza risposta. Fix: `catalog()` congela UNA snapshot di `_external_tools()`,
  costruisce i nomi dalla stessa snapshot, passa l'argomento opzionale `ext` a `tool_spec`
  e salta gli spec mancanti. Verificato: `/api/status` → 200 (era DROP), sweep live
  `tests/live/v199_endpoint_sweep.py` **51/51 PASS**; nuova suite `tests/v253_registry_catalog.py`
  (7/7) → battery **28/28 GREEN**. Nota: `filesystem` MCP non parte (`npx` mancante) → non
   c'entra col crash ma era il trigger.
- **JAG-254** *Tool MCP esterni pubblicizzati anche se assenti* (segnalato dall'utente: "un
  clone senza pmcp non li può usare, giusto?"): `config/tools.yaml` abilita `pmcp__gateway.*`
  e `python_sandbox__run_python_code` con `enabled: true`; `tool_spec` ritornava comunque uno
  spec (entry di config, `schema=None`) → `tool_context()` li elencava come chiamabili anche
  senza il server MCP. Fix: un tool esterno (`<client>__<tool>`) SENZA schema (server non
  connesso) ritorna `None` → mai pubblicizzato. Verificato: con `_external_tools()={}` il
  catalogo scende a 13 tool, 0 nomi esterni (`tests/v253` 11/11). Sul DGX (pmcp 26 + filesystem
  14 connessi) `/api/tools` = 53, 40 esterni, **0 traceback** dal restart. Il blocco PMCP nel
  system prompt era già condizionale (JAG-159: `server.system_prompt()`).
  *(Nota perf: la prima `/api/status`/`/api/tools` dopo un restart blocca ~20s su
   `_external_tools()→start_all()`; da rendere asincrono/bounded in un passaggio dedicato.)*
- **JAG-255** *WebUI: il messaggio dell'utente finiva DOPO la risposta* (segnalato
  dall'utente, sessione Jago): in `loadHistory` una risposta AI viene annidata nella
  card del nodo (`m.node`). Due turni che condividono lo STESSO nodo (es. n5) → la 2ª
  risposta finiva dentro la card creata per il 1° turno, che sta più in alto → la
  risposta compariva SOPRA la domanda a cui rispondeva. Fix: `nestScope()` annida solo
  se la card è stata disegnata a/after l'ultimo messaggio utente (`drawnIdx[nid] >=
  lastUserIdx`), altrimenti resta top-level. Riprodotto e verificato in DOM
  (chrome-devtools, sessione Jago): prima `[answer(34)] [YOU(35)]`, dopo `[YOU(34)]
  [CoT(35)] [answer(36)]`. Check di regressione in `tests/v240_ui_cli.py` → 24/24.
- **JAG-256** *Robustezza (2 fix)*: (A) `tools.execute()` chiamava `_dispatch_execute()`
  SENZA try/except → un tool che sollevava (es. `int("abc")` su un arg) propagava
  l'eccezione invece di dare un'observation pulita; ora qualsiasi crash del tool diventa
  `{"ok": false, "error": "tool crashed: …"}`. (B) Il system prompt assemblato veniva
  pubblicato come inject "system" ad OGNI turno (l'utente: "la harness rimanda il system
  prompt all'infinito") → ora de-duplicato per sessione via hash (`_LAST_SYS_INJECT`).
  Verificato: `tests/v256_robustness.py` 4/4, battery **29/29 GREEN**.
  Nota: `acp.py` era GIÀ protetto (try/except su `int(params...)`); il mio grep iniziale
  era un falso allarme.
- **JAG-257** *WebUI: difesa dal "run graph" di un'altra sessione nel pannello todo*.
  Al reload `loadGraph()` legge `sf_run` da localStorage e può dipingere il grafo di un
  run ESTERNO sopra il piano della sessione (i "vecchi todo" che riappaiono). Aggiunta
  la guardia `if (g.session_id && sessionId && g.session_id !== sessionId) return;`.
  Stato attuale (Jago): `sf_run=c60db6cec9b2` ≠ sessione, ma quel run è vuoto → il
  pannello mostra correttamente il piano della sessione (plan 1). **Non riprodotto** il
  sintomo esatto con i dati attuali → guardia = rete di sicurezza; da confermare con
  l'utente il comportamento preciso per un fix mirato.
- **JAG-258** *Context meter misurava con un modello DIVERSO dal turno* (segnalato
  dall'utente: "perché no autocompatta? sessione Jago, 99%"). Causa: il meter
  (`loadCtx` → `/api/context` SENZA `model`) usava il modello caricato sul router
  (n_ctx 32768 → 99%), mentre `prepare_session_for_turn` (trigger auto-compact) usa il
  modello della sessione (`win:nex-n2.5…`, budget 126976 → 22%). Due budget diversi →
  la barra diceva "saturo" ma la compaction (correttamente) non scattava. L'algoritmo
  NON era rotto: `context_engine.compact` su 24085 token → 3299 (compacted=133).
  Fix: il WebUI passa `model=currentModel()` a `/api/context`; nuovo helper
  `resolve_ctx_model(sess, model)` = explicit > session model > default, usato
  dall'handler (mai il modello caricato a caso sul router). Verificato dal vivo:
  server no-model 258048/10.9%, win-model 126976/22.1%; browser Jago = "ctx 28k/127k ·
  22% · normal" (era 99%/32768). Test `tests/v258_ctx_meter.py` **7/7**.
  **Residuo onesto:** per gli alias locali `context_budget` usa il `context_length`
  DICHIARATO (es. 262144) e non l'n_ctx REALE del router; per il modello `win:` il
  harness si fida dei 131072 dichiarati → da confermare lato Windows se il server gira
  davvero con quella finestra, altrimenti il prompt overflowa senza mai compattare.
- **JAG-259** *La finestra di contesto dei modelli LOCALI veniva dal valore
  DICHIARATO, non dal server* (continuazione di JAG-258). `providers.context_length`
  leggeva solo il `context_length` di providers.yaml: es. `win:qwen3.6…` dichiarava
  96000 mentre il server gira a **200000**, e i modelli SENZA dichiarazione cadevano
  sul default 32768 (compaction troppo aggressiva). Ora per i provider locali si legge
  la finestra REALE (`--ctx-size`/`n_ctx`) da `<base>/models`, in background
  (`providers.warm()` + cache TTL 600s, lookup case-insensitive), col dichiarato come
  fallback. Verificato dal vivo: win qwen3.6 **200000**, deepseek-r1 **100000**, gpt-oss
  **131072**, muse-glimmer **131072**, gemma **200000**; nex-n2.5 131072 (=dichiarato →
  il 22% di Jago era corretto). Test `tests/v259_ctx_subagent.py` **7/7**.
  Inoltre: (a) `subagent.spawn` ora onora il modello del ruolo **subagent**
  (`routing.role_model("subagent")` / `pick`) — prima la scelta nel WebUI era ignorata;
  (b) `chooseModel()` richiama `loadCtx()`, così la barra si aggiorna subito al cambio
  di LLM. Residuo: `win:qwen-3.8-27b-abliterated-q4` non è nel roster del server Windows
  → ctx 0 → default 32768 (modello di fatto non disponibile).
- **JAG-260** *WebUI: pannello **Context** spostato SOPRA **Plan / Tasks*** nella rail
  inspector (richiesta utente). Verificato nel DOM: `["Context","Plan / Tasks",
  "Approvals","Files & changes","Browser","Terminal","Feed"]`.
- **JAG-261** *`DEFAULT_BUDGET` 32768 → 262144 (256k)* (richiesta utente: "DEFAULT_BUDGET
  deve essere 256"). È il fallback SOLO quando non si sa nulla del modello (nessun
  alias, nessuna finestra live); con JAG-259 la finestra reale vince comunque.
  Verificato: `DEFAULT_BUDGET = 262144`, `context_budget(None) = 262144`; v258/v259 7/7.
  Nota: `/console` (Command Deck) legge `/api/context` senza model → con JAG-258 cade
  sul modello della sessione/default, quindi è allineato.
- **JAG-262** *Recovery degli orfani + log eventi interrogabile* (root cause della
  sessione Jago "bloccata"). **Causa REALE, provata da `events.db`:** il turno è
  partito alle 16:21; alle **16:28:15.87** il modello stava streammando la risposta
  finale (`chat.delta` "Ricerca web completata…") e **0.2s dopo** compare
  `service.start` (16:28:16): **un riavvio del servizio ha ucciso il turno a metà**.
  SIGTERM non esegue il `finally` → la sessione resta con un turno `user` orfano
  (nessuna risposta) e il grafo a metà → in UI sembra "bloccata". NON era un blocco
  del modello. Fix: (a) `reconcile_orphan_turns()` all'avvio: ogni sessione che termina
  su un `user` senza risposta riceve un turno assistant "⚠️ error: previous turn was
  interrupted by a service restart…" e i nodi `doing` tornano `todo`; (b) nuovo
  endpoint `GET /api/events?session=&kind=&since=&until=&limit=` + `forge events
  --session … --kind …` (post-mortem dal log durevole; il feed live replika solo per
  id); (c) `ERROR_PREFIX` tradotto (`⚠️ error: `). Verificato dal vivo su Jago
  (`session.reconciled`, n12 rilasciato, sessione chiusa); `v262_recovery.py` **9/9**;
  battery **32/32 GREEN** (aggiunti v258/v259/v262 al gate).
  **Lezione operativa: NON riavviare il servizio mentre un turno è attivo.**
- **JAG-263** *Il recovery è ora una capability dell'agente* (richiesta utente: "voglio
  che l'agente stesso sappia fare questa cosa e sappia quando farla"). Nuovo tool
  `reconcile` (schema in registry.py, dispatch in tools.py, `enabled`/`approval: auto`
  in config/tools.yaml): chiama `reconcile_orphan_turns(session=…)` → chiude l'orfano e
  libera i `doing`. La **descrizione** del tool dice al modello QUANDO usarlo: "quando
  una sessione sembra bloccata: ultimo messaggio `user` senza risposta E nessun turno
  attivo (`/api/chat/live` vuoto)"; `session` opzionale per ripararne una sola.
  Verificato: `/api/tools` → `reconcile enabled=True`; `tools.execute("reconcile",…)`
  chiude l'orfano; `v262_recovery.py` **15/15** (ora **18/18**).
- **JAG-262b** *Il reconcile non tocca MAI una sessione con un turno VIVO* (obiezione
  utente corretta: una sessione attiva ha come ultimo messaggio il `user` — la risposta
  si scrive solo alla fine — quindi uno sweep cieco la romperebbe). `reconcile_orphan_turns`
  ora salta ogni `sid in _ACTIVE_CHAT`. Aggiunti 3 check a v262 (live skippata, sessione
  intatta, recuperabile dopo la fine del turno). Battery **32/32 GREEN**.
- **JAG-264** *Il modello "impazziva" sui near-miss delle azioni* (segnalato dall'utente:
  "non ha senso, fammi capire questo chat design"). Due namespace di azioni: i **tool**
  usano `{"action":"tool","tool":"<name>","args":{...}}`, le azioni **harness/plan** sono
  TOP-LEVEL (`{"action":"write_todos","todos":[...]}`). Un modello piccolo li confonde:
  avvolge un'azione harness nell'envelope tool (`{"action":"tool","tool":"update_todos",
  ...}`) o emette il payload nudo senza `action`. L'harness lo rifiutava ("not a valid
  tool call") e ritentava all'infinito → il modello rimuginava sulla propria storia →
  **flood di eventi** (~40-72/s) → la WebUI sembrava bloccata. Fix: `_normalize_action`
  (server.py) riporta i near-miss alla forma corretta (envelope tool che contiene un nome
  harness → azione top-level; `todos`/`steps`/`note` nudo → `write_todos`/`update_todos`/
  `replan_todos`); un tool call o azione ben formati passano INVARIATI. Cablato in
  ENTRAMBI i loop (`chat_once` e `agent_run`). Test `tests/v264_normalize_throttle.py`.
- **JAG-265** *Anti-flood della chain-of-thought* (stesso incidente: la pagina "freeze"
  mentre server/CPU/HTTP erano SANI — 21599 eventi in 300s). Causa: i delta `think`
  streammano per token verso SSE **e** feed durevole; renderizzare ogni chunk con
  `textContent +=` forza un layout per chunk e la coda di rendering va in ritardo.
  Fix lato **server**: classe `ThinkCoalescer` (server.py) — i chunk `think` consecutivi
  vengono coalesciati in UN delta emesso al massimo ogni `CHAT_THINK_FLUSH_S` (0.08s) e
  una volta che il testo live raggiunge `CHAT_THINK_LIVE_CAP` (20000 char, poi marker di
  troncamento); un canale non-think scarica prima la CoT (ordine preservato); `flush()`
  a fine turno per la coda. Fix lato **WebUI** (index.html): `pushThink`/`flushThink`
  accorpano i delta in UNA scrittura DOM per animation frame (rAF); `cotFeed`/`_writeThink`
  limitano il testo live a `COT_LIVE_MAX` (40000). Test v264 (**19/19**). **Verificato in
  browser** (chrome-devtools): 200 `pushThink` sincroni → **0 scritture DOM** prima del
   flush, 1 blocco da 200 char dopo; cap → 40001 char con testa "…"; 0 errori console.
   Battery **33/33 GREEN**.
- **JAG-266** *Task list step-by-step come REGOLA FISSA + turni harness marcati*
  (richiesta utente: "non basta dirlo nel system prompt? inizio o fine? e i todo aperti?").
  Ricerca primaria in `docs/research/2026-10-04-multirequest-todos-and-reminders.md` +
  piano `docs/plans/2026-10-04-task-list-guidance-and-nudge-priority.md`.
  Implementate le parti SICURE:
  (a) nuova sezione statica `TASK_POLICY` (order 89, subito SOPRA `state` order 90) nel
      registro `prompt.SECTIONS`: regola standing "un passo alla volta, marca 'doing' prima
      e 'done' con evidenza, non batchare, MAI dire finito con passi aperti"; rimossa la
      frase duplicata da `CHAT_TOOL_PROMPT` (DRY);
  (b) `HARNESS_MARK = "[harness] "` + `harness_wrap()`: ogni turno sintetico dell'harness
      (nudge/osservazione/continue) è ora ETICHETTATO, così il modello lo distingue dal
      messaggio umano; la regola di priorità ("la richiesta dell'utente vince sempre; i
      messaggi `[harness]` sono contesto di sistema") è scritta in `TASK_POLICY`. Nota:
      `_inject` PRIMA iniettava come `role:"user"` senza marker (indistinguibile dall'utente).
  Test `tests/v266_task_guidance.py` **11/11**; battery **34/34 GREEN**.
  **Root cause trovato per il "todo restano aperti, l'harness non interviene"** (evidenza
  da `events.db`, sessione `86f0cfb0d728`): `plan.stopped reason=user_pivot open=10
  rounds=0` — `_user_pivot = bool(_open0)` è True quando il turno PARTE con todo aperti;
  se il modello non apre con un'azione di piano (`write_todos`/`update_todos`/`replan`), il
  primo `keepgoing.decide` (continue=True) viene sovrascritto a `user_pivot` → stop SILENZIOSO
  e la HITL è SALTATA (`if _open and _dec["reason"] != "user_pivot"`). Nei turni in cui il
  modello apriva con `update_todos`, `_user_pivot` veniva azzerato → il loop continuava
  (10→9→8→6 aperti) e "va un abomba".
  **FIX del pivot APPLICATO** (scelta utente: "non forzare il lavoro, ma fargli NOTARE i
  todo aperti e permettergli di chiuderli come 'superseded' con la ragione"):
  (c) `_pivot_decide()` + `_pivot_sync_text()` (server.py): su un pivot con todo aperti
      l'harness concede UNA sola "sync round" invece di fermarsi in silenzio — ricorda al
      modello i N todo aperti e gli permette di (a) chiudere con evidenza, (b) chiudere come
      **'superseded' CON la ragione**, o (c) replan; poi stop come `user_pivot` (nessuna
      forzatura: JAG-189 resta rispettato). Applicato a ENTRAMBI i siti di decisione.
  (d) nuovo stato todo **`superseded`** (CHIUSO, con `reason`) in `taskgraph`:
      `STATUSES`/`CLOSED_STATUSES`, `render_todos` mostra `[~]` + reason, `all_done`/`public`
      lo contano chiuso, `update_node` salva `reason`, `_apply_chat_todo_updates` passa
      `reason`, `TASK_POLICY` lo documenta, badge UI (`.st.superseded`).
  Test `tests/v266_task_guidance.py` **23/23**; battery **34/34 GREEN**.
- **JAG-267** *Context panel per categoria + dot-rail dei messaggi utente* (richieste
  utente #1 e #3; la #1 mostrava come riferimento la sidebar di TRAE).
  (1) `context_items(session)` (server.py) + `GET /api/context/items?session=`: deriva, dal
      SOLO transcript RITENUTO (`sess["messages"]`) + i file delle rule del workspace, le
      voci per categoria **Skills / Rules / Web Search / Files / Other**. Poiché legge ciò
      che è ANCORA in contesto, la compaction fa sparire da sola le voci scadute → il
      pannello si "resetta" da sé; **strettamente per-sessione, mai mischiate**. UI: chip per
      categoria + lista cliccabile (web→link, file→path) nel pannello Context.
  (2) **Dot-rail verticale** nella chat (`#dotrail`, index.html): un pallino per messaggio
      utente, l'ultimo = ultimo prompt; click → scroll al messaggio + flash; il pallino
      "corrente" segue lo scroll. Ricostruito dal `#log` corrente → si resetta al cambio
      sessione/clear.
  Test `tests/v267_context_items.py` **11/11**; battery **35/35 GREEN** (aggiunto v267).
  **Verificato in browser** (tab nuova, senza disturbare il turno in corso): 13 messaggi
  utente → 13 pallini, 5 chip. *Nota: l'endpoint backend si attiva al PROSSIMO restart (c'era
  un turno ATTIVO in `86f0cfb0d728` → restart rimandato); il dot-rail è puro client ed è già
  live.*
- **JAG-268** *update_todos mostra TUTTO il piano + no_progress solo su un giro
  davvero ozioso + regole già caricate* (richieste utente dal messaggio
  "ma no e detto che un todo sia un file..."). Tre fix:
  (1) `_apply_chat_todo_updates` (server.py) scriveva nel card SOLO le righe
      cambiate → sembrava "1/1 step updated" e il testo poteva trarre in inganno
      (es. una label che nominava un file). Ora l'output elenca l'INTERO piano
      (`plan_nodes`) come fa `write_todos`, oppure `no step changed` se nulla è
      cambiato; passa anche `reason` a `taskgraph.update_node`.
  (2) **falso positivo `no_progress`**: `_kg_stale` contava un giro come "stale"
      anche se giravano tool ma la LISTA non cambiava → stop dopo 3 giri di sola
      verifica (`plan.stopped reason=no_progress open=3 total=17 rounds=3
      dur=221.9s`). Nuovo helper `_next_stale(prev_stale, prev_hash, cur_hash,
      worked)`: azzera se il giro ha eseguito un tool (`work_steps > 0`) o se la
      lista è cambiata; incrementa solo se davvero ozioso. Applicato a entrambi i
      siti (chat loop ~3000, agent loop ~3299).
  (3) `rules.py`: l'intro ora dice esplicitamente che il testo delle regole è
      **già caricato** sotto ("so you do NOT need to open these files — read them
      only if you intend to edit"); marker di troncamento `[troncate]` → `[truncated]`.
  Test `tests/v266_task_guidance.py` **28/28** (aggiunti i check JAG-268); battery
  **35/35 GREEN**.
- **JAG-269** *Un todo è un OGGETTO indirizzato per ID (id-first) + motivo di
  chiusura obbligatorio* (richieste utente "se chiude un todo deve scrivere la
  motivazione? / perché non usano i CODICI ID dei todo?"). Principio: tutto ciò
  che riguarda un todo vive DENTRO l'oggetto del suo id — mai indicizzato per
  posizione. Audit: il **data model**, l'**API** (`/graph/nodes`), il **loop
  agent** (`map_action`), il **WebUI** e le **sessioni** erano già id-based;
  l'unico punto index-based era il **contratto insegnato al modello** nella chat.
  Fix: (1) `update_node` ora **RIFIUTA** un `superseded` senza `reason` (come
  `done` esige l'evidence) — [taskgraph.py:368-375]; (2) il prompt chat insegna
  id-first (`{"steps":[{"id":"<node id>","status":"doing"}]}`, `index` resta come
  fallback) nei 3 siti: `CHAT_TOOL_PROMPT`, `TASK_POLICY`, `_pivot_sync_text`;
  (3) il card `update_todos` **e** `write_todos` mostrano ora l'**id** e, per uno
  step chiuso, la **reason** (`- [~] n12 label  (superseded: why)`); (4) una
  chiusura rifiutata NON viene più ingoiata: `update_todos` torna `ok=False` con
  `stderr` che nomina la reason mancante, così il modello impara; (5) un `dep`
  stringa può essere un **id di nodo** (o una label). Test
  `tests/v269_id_first_todos.py` **18/18**; battery **36/36 GREEN** (aggiunto v269).
- **JAG-270** *Pannello Context: occupazione token per categoria + item apribili
  nell'editor + composer più piccolo* (richieste utente #1/#2: "skills and files …
  shall open when clicked, open in the editor … relevant to context percentage
  occupation can you compute it?").
  (1) `/api/context/items` ora calcola l'**attribuzione token** per categoria
      (`tokens`: skills/rules/web/files/other/harness/conversation) leggendo il
      transcript (`[harness] Observation for tool X` → X; reminder `[harness]` →
      harness; il resto → conversation) + i token del blocco regole (system prompt).
      Ritorna anche `budget_tokens`/`used_tokens`/`pct` reali (stesso
      `context_usage` del ctx meter); `tokens_total` = somma. Gli item **file/rule/
      skill** ora portano un `path` REALE (skill risolte via `skills.list_skills()`
      → SKILL.md) così la UI li apre nell'editor.
  (2) WebUI: l'intestazione del pannello mostra `context N% · used/budget tok`; i
      chip mostrano anche `~tok` per categoria; **click su file/regola/skill → apre
      nell'editor** (`SparkEditor.open`); "Other" ha tooltip "tool output carried in
      context — non è un file/web/skill" ed è l'unico non apribile (sono i tool non
      specializzati, es. shell: non c'è nulla da aprire).
  (3) `#inp` (composer) `font-size: 13px` (ereditava 14px dal body → troppo grande).
  (4) `.tcid` (`J1.T17`) ora ha `title="node id n17"`: chiarisce che J1.T17 è una
      label umana derivata dall'id, **non** l'indice.
  Test `tests/v270_context_occupancy.py` **15/15**; battery **37/37 GREEN**.
  *Nota: il restart per attivare backend/UI è RIMANDATO — al momento del commit un
  turno era ATTIVO in `86f0cfb0d728` (`/api/chat/live` non vuoto).*
- **JAG-271** *Nudge con gli step ESATTI + STOP affidabile + prompt cache-safe*
  (4 richieste utente: nudge preciso; ottimizzazione/allineamento; "il system prompt
  viene ridato ad ogni messaggio"; "STOP non ferma l'LLM alla GPU").
  (1) `_open_todo_brief(sess)` + `_nudge_open_todos(sess)`: il nudge post-update
      elenca gli step APERTI esatti (id + status + label), non più il vago
      "mark the next step 'doing'". Usato dopo `update_todos` e `write_todos`.
  (2) **STOP — root cause trovato**: `stopRun()` (WebUI) mandava `/api/chat/abort`
      SOLO se `turnSSE[sessionId]` esisteva; ma il worker server NON è legato alla
      richiesta (JAG-168) → se l'SSE cade, o il turno è nato in un'altra tab, il
      click non mandava NULLA e la GPU continuava a decodificare. Ora l'abort si
      manda SEMPRE (idempotente, innocuo se idle). Prova empirica controllata
      (`trash/test_stop.sh`): util GPU 0% → 93% (generazione) → abort → **0% in ≤3s**,
      stream congelato, `active: []`. Quindi il server ferma la GPU: il buco era l'UI.
  (3) **Prompt cache-safe** (ricerca web → `docs/research/2026-10-04-prompt-caching-
      system-prompt-and-nudge.md`): l'API è **stateless**, il system prompt VA
      rimandato ogni turno (non è evitabile); la leva vera è il **prefix caching**.
      Riordino `prompt.py:SECTIONS`: TUTTE le statiche prima (order 10..40), poi le
      dinamiche (50..70), poi `task-policy`(89)+`state`(90) ultimi (regola JAG-266
      preservata). `self_summary()` verificato statico (nessun timestamp) → il front
      è byte-stabile e llama.cpp riusa la KV di prefisso.
  Test `tests/v271_prompt_alignment.py` **14/14**; battery **38/38 GREEN**.
- **JAG-272** *Ctx breakdown che SOMMA al totale + solo file reali apribili + inspector
  compatto + guard anti-LLM-stupido* (4 richieste utente).
  (1) **I numeri non sommavano** (tokens_total 1127 vs used 5178): `context_items`
      ora attribuisce anche il SYSTEM PROMPT per sezione (`prompt.section_texts`) →
      bucket system/tools/rules/skills/memory/plan + transcript + `overhead` (gap vs
      il conteggio reale del router). `sum(tokens) == used_tokens` (test: 4412==4412).
      UI: barra impilata + legenda `label tok %`.
  (2) **File finti non apribili**: `api_v02.py` → `/sparkforge/api_v02.py` (inesiste)
      → l'editor non apriva. Ora i path sono VALIDATI (relativi risolti su
      workspace/repo): restano solo file REALI (niente click morti / spazio sprecato).
  (3) **Inspector compatto**: rimossa la card "Editor" ridondante + h2/card più strette
      → "Files & changes" occupa molto meno.
  (4) **Guard anti-LLM-stupido**: dopo 4 turni invalidi CONSECUTIVI (JSON/azione) STOPpa
      con reason `no_valid_action` (+ evento) invece di bruciare le 64 iterazioni.
  Test `tests/v272_context_accounting.py` **13/13**; v267/v270 aggiornati (path reali);
  battery **39/39 GREEN**.

### Memoria generica (Hindsight MCP)
- Le lezioni *generiche* di ingegneria imparate qui sono state salvate via MCP
  Hindsight (`retain`, bank `cccc-shared`): scritture atomiche con temp unico,
  cancellazione cooperativa, read-modify-write nel lock, fallback che rispetta
  cancel, handler HTTP graceful, progressive disclosure delle capability.

### Test LIVE (richiedono il server up) — cartella `tests/live/`
- `v199_endpoint_sweep.py` (51/51), `v200_concurrent_chat.py` (7/7),
  `v202_concurrent_stream.py` (4/4), `v208_chaos_http.py` (22/22, caos/abuso HTTP +
  malformed query + session-id traversal + wire-type abuse + svg preview + wire-crash
  payload JAG-233..236; NON persiste più sessioni),
  `v213_deck_live.py` (11/11, smoke del deck deployato: /console pubblico + alias,
  dati auth-gated, feed SSE), `v216_planner_async.py` (5/5, il planner non blocca
  più il `done`). NON nel gate `battery.sh`.

Battery: v140 9/9, v177 OK, v183 28/28, v195 21/21, v198 26/26, v204 23/23,
v205 13/13, v206 10/10, v207 28/28, v209 18/18, v210 27/27, v212 19/19,
v214 15/15, v215 8/8, v217 7/7, v222 8/8, v225 13/13, v226 11/11,
v229 26/26, v230 25/25, v231 21/21, v232 8/8, v233 28/28, v238 14/14, v240 24/24,
v247 35/35, v251 22/22, v253 11/11, v256 4/4, v258 7/7, v259 7/7, v262 18/18,
v264 19/19, v266 28/28, v267 11/11, v269 18/18, v270 15/15, v271 14/14,
v272 13/13 → **39/39 GREEN**.

### Test: convenzione nomi (richiesta utente punto 0/4)
- Cartella `tests/`, file `v<NNN>_<slug>.py` (numero = ticket JAG, slug descrittivo).
- Gate ufficiale = `tests/battery.sh` (v140, v177, v183, v195, v198, v204, v205,
  v206, v207, v209, v210, v212, v214, v215, v217, v222). Usa `PYTHONPYCACHEPREFIX` su temp (niente bytecode stale).
- Suite "hard/bastarde" = `v195_hard.py` (da riusare per regressione SOLO se c'è
  motivo concreto). Scenari etichettati A..I con `check("Xn ...")`.
- `tests/legacy/` = accettazione storica, NON parte del gate.
- Aggiungere nuove suite avanzate come `v195_hard.py` per tema, non una per bug.

---

## 2. TODO (richieste utente, in ordine)

- [ ] **(0)** I test hard piacciono: mantenerli, nominati, riusabili. Non gonfiare
      il gate: nuova suite solo se aggiunge copertura.
- [ ] **(1)** README/descrizione: pubblicizzare SOLO le parti UNICHE vs harness note
      (PRM/best-of-N, verifier gate, tool-output offload, context budget onesto,
      task graph LLM inline, SSE feed, MCP client, subagent, memoria). Fare ricerca
      web sulle harness 2026 per calibrare. → vedi `docs/research/`.
- [x] **(2)** Ricerca skills/MCP loading: FATTO →
      `docs/research/2026-10-04-harness-frontier-and-our-niche.md`. Il nostro
      meccanismo era già allineato (L1 name+desc sempre, L2 body on demand); lacuna
      chiusa = ricerca skill (JAG-198). MCP: schemi up-front, nessun retrieval
      dinamico (candidato futuro se >~50 tool).
- [x] **(3)** Documento problemi AI + come li risolviamo: FATTO (tabella
      failure-mode nella doc di ricerca).
- [x] **(3b)** Test consapevolezza skills/tools: FATTO →
      `tests/v198_skills_tools_awareness.py` (19/19): prompt dichiara tool+skill,
      dice di SCAN/LOAD, e ora di SEARCH.
- [ ] **(4)** **BUG HUNT frontier**: provare ogni endpoint/pulsante/flusso WebUI e
      combinazioni sempre più complesse. Valutare benchmark ufficiali sugli
      endpoint dell'harness (NON cose da ore). Cartella test ben nominata.
- [ ] **(5)** Ricerca harness futuristiche → confronto → **RDD** (research-driven
      development) per migliorare.

---

## 3. PROSSIMO PASSO IMMEDIATO

### Fatto ORA (2026-10-04, sessione corrente — bug hunt sistematico + contesto)
1. Surface-fuzz live (~1100 richieste) → **5 classi di crash che DROPPAVANO la connessione**,
   tutte corrette: JAG-233 (`_send(None)`), 234 (`meta` label), 235 (`run_get` unhashable),
   236 (`acp connect`), 237 (`mcp disconnect_all` race). Test `v233` (28/28) nel gate.
2. **Contesto/sessione** (domanda utente): sessione a 195% = **junk dei miei test** (2MB).
   `/api/context` droppava su content non-stringa → la UI lasciava il % vecchio. Fix JAG-238
   (`count_tokens` coerce, `/api/chat` richiede str, `loadCtx` reset su errore) + test `v238`.
   **Sessions NON condividono il contesto** (verificato API + browser). Auto-compact a 75%
   solo a inizio turno e non riduce un singolo messaggio gigante (per design).
3. **Pulizia**: cancellate le sessioni junk; **isolamento test** (v208 non persiste più, JAG-239).
   v208 → 22/22, battery → **24/24 GREEN**.
4. **Da approfondire (residui onesti)**: `/api/meta` e `/api/mcp/reload` sono lenti (LLM-based /
   pmcp 21.8s) — non bloccano il server (thread) ma il client; valutare async/limite. Il
   meter mostra il *carry* intero (può superare 100% con un messaggio enorme) mentre il prompt
   spedito viene troncato: valutare un indicatore "carry vs inviato".

### Storico (sessione precedente — punti 0-5 avviati)
1. Ricerca web harness/skills/MCP/failure-modes → doc in `docs/research/`.
2. `tests/v198_skills_tools_awareness.py` (19/19) + `skills{action:"search"}`.
3. Test live `tests/live/` (v199 endpoint sweep 51/51, v200 7/7, v202 4/4).
4. Bug trovato e risolto: **JAG-201** (concorrenza stessa sessione).
5. **RDD in corso** — P5 (audit skill, JAG-203), P2 (verifica memoria, JAG-204,
   con bug parser reale corretto). Prossimi P1 (step auditor) e P3 (budget).
6. **Punto 2 RDD** (fondamento del "loop sigillato"): JAG-205 gate held-out esterno
   hash-pinnato, `promote` fail-closed. Spec+piano+test. Prossimo: applicarlo ad
   altri target (skill/prompt/tool) e costruire il vero step auditor (P1).

### Prossimi bug-hunt frontier (NON ancora fatti)
- **Steer** durante un turno (`/api/chat/steer`) → il modello lo applica al confine?
- **Abort** durante un turno AGENTICO con tool (non solo risposta semplice).
- **DELETE sessione mentre un turno gira** → worker orfano? (noto: `DELETE` non
  abortisce un turno attivo).
- **Ricarica (reload) fidelity** dopo un turno reale con tool-cards/inject.
- **Compaction** (`/api/context/compact`) → preserva task list + reply?
- **`/api/agent/run`** concorrente + `/api/agent/control` abort.
- Confronto con benchmark ufficiali (SWE-Bench-style) sugli endpoint, ma corti.

### Backlog RDD (da `docs/research/...our-niche.md`)
- Schemi MCP differiti sopra ~50 tool.
- Step auditor read-only (LongHorizon Manage-Execute-Audit).
- Metrica goal-drift (GD_actions/GD_inaction) nei runmetrics.

---

## 4. FILE/HANDOFF CORRELATI
- `docs/TESTING-PLAYBOOK.md` — come testare live.
- `docs/research/harness-frontier-2026.md`, `harness-frontier-v3.md` — ricerca
  precedente sulle harness.
- `docs/research/2026-10-04-multirequest-todos-and-reminders.md` — come le
  harness (Claude Code/SDK, LangGraph, deepagents, OpenAI Agents SDK, Cline,
  Aider, OpenHands) gestiscono reminder di completamento todo, richieste
  multiple non correlate nella stessa sessione (nuova lista vs append), e
  priorità messaggio utente vs reminder dell'harness. Fonti primarie.
- `docs/plans/`, `docs/specs/` — piani e design.
- `tests/legacy/v095_prm.py`, `v145_bestofn.py` — PRM / best-of-N (parte unica).

---

## JAG-272 — DEFERRED RESTART (record 2026-10-04 18:51)
- JAG-272 committed `b229c39` + pushed, tests v272 13/13, battery 39/39 GREEN.
- The running service was still on the JAG-271 build (last restart 18:35:38;
  JAG-272 committed 18:45:15) -> the new `context_items.breakdown` and the
  `_invalid_streak` guard were NOT live.
- A service restart was NOT done immediately because the user's `Jago_session`
  (`86f0cfb0d728`) had a LIVE turn (synchronous `subagent` research running).
- Deferred restart automated via a detached watcher:
  `trash/watcher_restart.sh` (launched by `trash/start_watcher.sh`, pid logged
  in `trash/watcher_restart.log`). It polls `/api/chat/live` every 10s and runs
  `systemctl --user restart sparkforge.service` as soon as `active` is empty.
- After restart: verify `/api/context/items` now returns `breakdown` whose
  `sum(tokens) == used_tokens` (was the user's point #1).

---

## JAG-273 — token/cache optimization + junk sweep (2026-10-04)
### 2a — duplicated task list removed
- `render_todos(graph, limit, compact=False)`: `compact=True` lists ONLY the open steps
  + a `(+N closed …)` line and DROPS the ownership paragraph (already in the static
  `task-policy`). `context_summary` (the always-on `state` section) uses `compact=True`.
  Measured 131 vs 468 chars on a 3-node list.
- The keepgoing CONTINUE/pivot injections no longer re-paste the FULL list
  (`render_todos(taskgraph.load(...))` gone) — they use `_open_todo_brief(sess)[1]`.
### 2b — cache-safe order (prompt.py)
- `task-policy` moved 89 -> 45 so EVERY static section precedes EVERY dynamic one (a
  static rule no longer sits after a dynamic block). `memory` moved 70 -> 80 (last
  dynamic); `state` stays last. Trade-off: task-policy is no longer immediately above
  `state` (JAG-266) — the rule still names `Harness state` explicitly. v271 test updated
  to the STRONGER content-based invariant.
### 2c — real cache-hit meter
- The router returns the prefix-cache hit: `usage.prompt_tokens_details.cached_tokens`
  (and `timings.cache_n`). Proven live: two identical calls -> 0 then 1097/1101 = 99.6%.
- `server._REAL_CACHED_TOKENS` captures it in `_record_usage`; `context_usage` +
  `context_items` expose `cached_tokens`/`cache_hit_pct`; WebUI ctx header shows `cache NN%`.
### Junk sweep (dead code, verified zero references)
- meta.py: unused `from . import approvals as appmod`.
- removed: `server.extract_actions`, `server.breakdown_tasks` + `BREAKDOWN_PROMPT`
  (superseded by the task GRAPH; nothing called them), `runmetrics.human`,
  `otel_tracing.provider_ready`, `subagent.handle_agent_action`, `approvals.pending_count`,
  `verify.snapshot` (tools.py builds the pre-image inline), `providers.is_local`.
- WebUI: dead `tasks.breakdown` listener + `loadGraphSoon` + `_tasksT` removed.
### Verification
- `tests/v273_cache_and_cleanup.py` 26/26; `v271` updated; battery → **40/40 GREEN**.
- NOTE: service restarted 18:53:54 (activating JAG-272). JAG-273 needs one more restart.
### STILL OPEN (recommended, NOT done — needs its own task + tests)
- `state` lives in the SYSTEM prompt, i.e. BEFORE the transcript. When the task list
  changes, the KV cache is invalidated from there ONWARD — including the whole
  transcript. The Claude-Code pattern (move the live list into the CURRENT user turn,
  after the transcript) would let the system prompt + old transcript stay cached:
  potentially the single biggest cache win, but it changes what the model sees as
  system vs user and touches the ctx attribution, so it needs a dedicated pass.

---

## JAG-274 — chat/todo UI coherence (2026-10-04)
### The problem (user, verbatim gist)
The chat read as "uno schifo": the newest work was buried UP inside an old todo
card; a step's history was recollected under the step while the live work scrolled
away; the re-plan appeared BELOW the list it produced; clicking a sidebar todo did
nothing to the chat.
### Design chosen by the operator (AskUserQuestion)
- chat layout = **"Stream + sezioni step"** (one chronological stream; a todo =
  an inline collapsible section);
- sidebar re-plan = **"update + show only"** (no hidden LLM turn);
- note: *"the replan and the continuation must be triggerable by the LLM itself, as
  a tool … the agent must be able to use the whole harness"*.
### Implemented
1. Sticky `#nowbar` (markup + CSS): shows the ACTIVE step (`J1.T20 doing label`)
   + the latest activity (`→ <tool>`); click jumps to the step. So you always see
   what the agent is doing NOW even when the step scrolled up.
2. Chronological stream: `_openSection(nid)` reuses a step's section ONLY while it
   is still the LAST element of `#log`; otherwise it opens a FRESH section at the
   bottom -> resumed work is never buried "up". `_chatSections[id]` = all sections,
   `_chatNodes[id]` = the latest (repaint + sidebar scroll).
3. `loadHistory` rewritten to ONE `ts`-ordered stream (`evs`) of messages +
   tool_cards + injects. The stored `after` is unreliable after a compaction, so
   ordering uses `ts` (fallback: the ts of the message at `after`). User turns stay
   top-level (the chronology anchor).
4. Sidebar todo click -> `showNodeDetail(n)` AND `_scrollToNode(n.id)` (jump the
   chat to that step's latest section + flash + tooltip).
5. `replanGraph`: the `↻ re-plan: +N node(s) — labels` announcement is drawn FIRST
   (forced top-level), THEN the new steps below it; cancel guard (`note === null`).
6. `graph.replanned` feed listener: the server publishes it on a sidebar replan, so
   the chat + Plan panel refresh without a manual reload.
7. Server `graph_post` replan branch publishes `graph.replanned` and deliberately
   does NOT inject a chat turn (operator choice). The LLM still owns re-planning as
   an ACTION: `replan_todos` (documented in CHAT_TOOL_PROMPT / TASK_POLICY / pivot,
   handled by `_replan_todos`), NOT a separate `tool`. Continuation is harness-driven
   (the keepgoing loop while steps are open); the model drives it by marking steps
   doing/done.
### Verified
- `tests/v274_chat_stream.py` **25/25** (static invariants);
  `tests/v240_ui_cli.py` JAG-255 checks migrated to the open-at-bottom rule;
  battery -> **41/41 GREEN**.
- Browser (chrome-devtools, page 13, after restart): **0 console errors**;
  reopening a step after another opened a NEW section (2 sections, latest is last);
  `_scrollToNode` returns true; the sticky bar renders `J1.T20 doing … → web`.
- Service restarted 19:29:21 (activating the server-side `graph.replanned` publish).

---

## JAG-275 — change REVIEW flow + compact rail + chat timestamps (2026-10-04)
### Requests (user)
1. "i diff si annullano se vengono approvati cosi dovrebbe essere" -> a change must
   NOT stay "a vita": each change is REVIEWED. Approve = keep the file as written and
   clear it from the list; Reject = undo (restore the pre-image / remove a created
   file). Plus approve-all / reject-all. The diffs are kept UNTIL you decide.
2. "tasti troppo grandi" -> compact the rail buttons.
3. "data e ora delle risposte ... nella chat piccolino" -> a small date+time stamp
   on every chat turn (user / harness / LLM / tool card).
### Implemented
- edits.py: `approve(key, path=None)` drops the pending entries WITHOUT touching the
  files; `undo` remains the REJECT. Endpoints `POST /api/edits/approve` (and a
  `/api/edits/reject` alias). The panel is now "Pending changes".
- WebUI: every change row has ✓ / ↩; the panel and the chat chip have
  "✓ approve all" / "↩ reject all"; the diff modal has approve + reject.
  `undoEdits` kept as a thin alias.
- Rail buttons: `#inspector button.ghost { font-size:11px; padding:4px 9px }`.
- Chat timestamps: `_tsSpan(ts)` (small "MM-DD HH:MM:SS") rendered in `who()`
  (user + LLM), the CoT header, `harnessInject` and `toolCard`; live = now, history
  replay forwards the stored `ts`.
### Verified
- `tests/v275_changes_review.py` 22/22; `tests/v274_chat_stream.py` updated;
  battery -> **42/42 GREEN** (v275 added).
- Browser (chrome-devtools): 0 console errors; rail button 11px/`4px 9px`; 805
  timestamps rendered (first "10-04 00:41:37"); approve-all/reject-all present.

## JAG-276 — move the live task list into the current USER turn (cache) (2026-10-04)
### Why
The `state` section (the live task list) was the LAST section of the SYSTEM prompt.
Any task-list change invalidated the KV prefix FROM THERE ON, so the whole
transcript was recomputed each turn. Moving it into the LAST user message (which
changes every turn anyway) keeps the system prompt + committed transcript
byte-stable — the Claude-Code cache pattern. This was the "STILL OPEN" item from
JAG-273.
### Implemented
- prompt.py: removed the `state` section + `_provider_state`; SECTIONS now ends at
  `memory` (order 80) and the system prompt is 100% static at the front.
- server.py: new `state_block(session_id, graph_key)` (wraps `context_summary`).
  `assemble_turn` appends it to the user message; `context_usage` mirrors it (the
  meter counts it); `context_items` attributes it to the `plan` bucket;
  `agent_run` and `api_v02.run_agent` moved it from the system prompt into the user
  turn (v2 refreshes it each iteration).
- Wording: TASK_POLICY / `_pivot_sync_text` / CONTINUE nudges now say the list is
  "at the end of your current message" (was "above").
### Verified
- v266/v271/v273 updated to the STRONGER invariant: the system prompt carries NO
  live task list; `assemble_turn` injects it in the LAST user turn.
  v270/v272 attribution still sums to the total (plan bucket preserved).
  battery -> **42/42 GREEN**.
- Live (restart 19:49:53): `/api/edits/approve` -> 200 clean JSON; the only
  "Harness state (your persistent task list)" string left is inside `state_block`.

---

## JAG-277 — English-only sweep: translate Italian comments/docstrings/logs (2026-10-04)
### Why
The standing "English-only" rule was still violated: many modules carried Italian
prose in comments/docstrings (verify, server, keepgoing, selfevolve, ...). Code,
comments, docstrings, logs and UI strings must be English.
### Done
- Translated all Italian natural-language prose (comments, docstrings, human-readable
  log/error messages, generated-template text) to English in 12 modules: server.py,
  selfevolve.py, keepgoing.py, verify.py, difficulty.py, bestofn.py, heldout.py,
  improve.py, skills.py, tools.py, runmetrics.py, prompt.py.
- Deliberately NOT changed (they are logic/contracts, not prose): identifiers,
  dict/JSON keys, regexes, event kinds, markers ("[harness] "), tool names, prompt
  section ids, and the big prompt/policy constants (already English). The Italian
  matcher inside `_looks_like_promise` and the HITL string "In pausa" (asserted by
  tests/legacy/v171) were left untouched.
### Verified
- `python3 -m py_compile src/sparkforge/*.py` -> exit 0.
- Residual-Italian scan across src/sparkforge -> none.
- battery -> **42/42 GREEN**.

---

## JAG-278 — justified 'superseded', recognizable actions, denser Context, TRAE-style composer (2026-10-04)
### 1) GRAVE — a 'superseded' must be JUSTIFIED (user)
Live evidence (session 86f0cfb0d728): the model force-closed 5 OPEN steps as
'superseded' with reasons that said the work was STILL open ("il lavoro resta
aperto"). A reason WAS present, so JAG-269's non-blank check passed — but it was a
NON-justification. Fix:
- `taskgraph.update_node`: a 'superseded' reason that READS AS STILL-PENDING is now
  REJECTED (phrase guard: "resta aperto/da", "rimane da", "remains open",
  "still pending", "not complet", ...) and the error tells the model to LEAVE IT
  OPEN if the work is still wanted.
- `TASK_POLICY` + the pivot reminder now state: superseded = PERMANENTLY abandoned,
  leaving steps OPEN is the DEFAULT, and a still-open reason is REJECTED.
- UI: the reason is shown inline on the chat card (`.tcreason`) and in the node detail.
### 2) "not a valid tool call" during continuation (user)
The model's own thinking admitted "update not recognized" — 61 turns were wasted on the
opaque retry. Fix:
- `_normalize_action`: an UNKNOWN action NAME with a recognizable PAYLOAD (steps/todos)
  is coerced by SHAPE; an OpenAI-style function call {"name","arguments"} -> tool; a
  tool envelope with "name"/"tool_name" -> tool.
- a made-up "I am done" envelope ({"action":"answer"/"finish"/...}) is treated as the
  plain-text answer instead of a retry (`_term_action`).
- the retry now NAMES the emitted action ("You emitted: {...}") so it is diagnosable
  and teachable, instead of a blind loop.
### 3) UI: Context panel + composer (user)
- Context: ONE horizontal row (% · bar · state · compact) — the tall `.ctxbig` block is
  gone, saving vertical space.
- Composer (TRAE-style): the model picker MOVED from the header INTO the composer bar
  (opens upward); new "+" menu (attach a file path / paste text / workspace files /
  commands / skills); attachment chips above the input; voice input via the Web Speech
  API (browser-native — no server dependency, no whisper install).
  HONEST limits: an "image" attach sends a PATH reference (the text models cannot see
  pixels; a vision model would be needed); voice works in Chrome/Edge with a mic, so on
  the DGX (no mic) it is a graceful no-op.
### Verified
- `tests/v278_supersede_guard.py` **24/24**; battery -> **43/43 GREEN**; py_compile clean.
- Browser (chrome-devtools): 0 console errors; the "+" menu renders 5 items; an
  attachment chips and `_attachBlock()` builds the prefixed block; the model picker is
  inside `#composerBar`; `.ctxbig` gone; the Speech API is present.

---

## JAG-279 — real attachments, pickers, copy-all-URLs, voice help (2026-10-04)
Live UI feedback (Giovanni). The JAG-278 composer was a half-stub; this closes it.
### 1) "+" menu was broken (user)
- "Attach a file" popped a browser `prompt()` asking for a PATH (impossible to know
  from a browser, and meaningless across a Windows client / Linux server split).
  -> native `<input type=file>`: the picker SENDS the bytes, the server stores them
  and returns a real absolute path the model can `fs.read`.
- "Workspace files" just opened the editor -> now a searchable workspace-file picker
  (`/api/fs/list`, folder navigation + attach).
- "Skills" typed a literal `/skill ` (not even a valid skill name) -> now a searchable
  skill picker (`/api/skills`) that inserts `/<name> `.
- "Paste text" used `prompt()` -> now a proper modal.
### 2) Web-Search copy (user: for NotebookLM)
- The Context panel's Web Search list now has a curated "⧉ copy all URLs" button
  (one URL per line) + a per-URL copy button on each row.
- `copyText()` is secure-context-aware: `navigator.clipboard` on https/localhost,
  legacy `execCommand` fallback on a plain-HTTP LAN origin (so copy works from the DGX).
  A toast confirms.
### 3) Voice permission (user)
- Root cause: the UI is served over plain HTTP on a LAN IP = an INSECURE ORIGIN, so
  browsers block the microphone entirely (it is not a "setting" to flip silently).
- The mic button no longer fails silently: `voiceHelp()` explains the exact remedies
  (SSH tunnel to `http://localhost:8790`, or the Chrome/Edge
  `unsafely-treat-insecure-origin-as-secure` flag) plus where to grant permission.
  Web Speech API stays browser-native — no whisper dependency.
### Backend
- `POST /api/attach` (raw body) -> `api_v02.attach_save()` stores under
  `data/attachments/<session>/`, sanitizes the name + session (no traversal),
  dedupes by timestamp instead of overwriting, rejects empty/oversize (`SPARKFORGE_ATTACH_MAX`).
### Honest limits
- An "image" attach sends a PATH reference + the raw file on disk; the harness models
  are TEXT models and cannot see pixels (a vision model would be required to "process" it).
- Voice still needs a real microphone on the machine running the browser; on the DGX
  (no mic) it stays a no-op even after the origin is fixed.
### Verified
- `tests/v279_composer.py` **28/28**; battery -> **44/44 GREEN**; py_compile clean.
- Browser (chrome-devtools, page 16): 0 console errors; the "+" menu renders 5 items;
  a live upload to `/api/attach` returned `{ok:true, path, size}`; the Web-Search
  category shows the copy-all + per-URL buttons; the workspace picker (1 row for a
  1-file workspace) and the skill picker (179 rows) both open; `copyText` returns true
  on the insecure origin; `voiceHelp` opens and names the Chrome flag.

---

## JAG-281 — real terminal, model popover, browser copy, max-context + thinking effort, best-of-N/self-evolve in the gate (2026-10-04)
Autonomous sweep of six user points.
### 1) LLM model menu (user: opens too far right, too transparent)
- `#modelMenu` was `position: fixed; bottom:92px; right:16px` (pinned to the
  corner, detached from the trigger) with a translucent `var(--panel2)`.
  -> wrapped `#model-btn` + `#modelMenu` in `.model-wrap{position:relative}` and
  made the menu `position:absolute; right:0; bottom:calc(100% + 8px)`, opaque
  `#0f1320`. Verified: menu.bottom <= button.top, right-aligned, bg rgb(15,19,32).
### 2) Browser panel: copy all URLs (user)
- Search/fetch results now expose a "⧉ copy all URLs (N)" button that copies every
  URL found, one per line (deduped), same clipboard helper as the Context panel.
### 3) Real terminal (user: "must be the real terminal, not what you wrapped")
- ROOT CAUSE of the wrapper: the old panel was a one-shot front-end over the gated
  `shell` tool — a fresh stateless process per Enter (no `cd`/env survival, output
  buffered until exit). It was wrapped to reuse the agent's approval gate.
- NEW `term.py`: a PERSISTENT `/bin/bash` per session — cwd, env and shell state
  survive across commands, output streams live via `/api/term/poll` (cursor),
  with a completion sentinel `__SF_DONE__<code>`. Endpoints:
  `POST /api/term/exec`, `GET /api/term/poll`, `POST /api/term/reset`. UI: cwd
  header, clear/reset, ↑/↓ history. Verified live: `echo ui-term-ok` streams and
  `cd /tmp` then `pwd` returns `/tmp` (persistence proven through the UI).
- SECURITY (deliberate): this is the HUMAN terminal (the operator typing) and it
  runs directly; the AGENT's `shell` tool keeps its approval gate. Reachable only
  behind the harness token (the whole HTTP surface is auth-gated).
### 4) Can the harness use all of itself? (user question) — YES
- `fs.read/write/edit` roots are `["." , "/home/jagones/Repositories"]` and `.`=the
  sparkforge repo, so it can read/edit its own source; `shell` runs `tests/battery.sh`;
  `subagent` spawns nested runs (depth cap 2); `skills`/`improve`/`selfevolve` grow
  its own skills. Honest caveats: `sandbox.backend: none` runs on the host and
  `approvals.mode: full` currently auto-approves — so self-edits are unapproved.
### 5) Models: max context + thinking effort (user)
- Answer to "is context taken from the model?": context_length is LIVE for local
  llama.cpp (`n_ctx`), from the OpenRouter catalogue for OpenRouter, else DECLARED.
  `budget_tokens = context_length - 4096`. The provider form could not set it.
  -> the models field now accepts `id:context_length` (e.g. `gpt-5.1:400000`), with
  an inline hint.
- Thinking effort: NEW opt-in setting -> adds `reasoning_effort` to the request
  body ONLY when enabled and a valid value is set (safe default: the body is
  byte-identical when off, so plain/local models are never affected). Values:
  minimal/low/medium/high (OpenAI-compatible reasoning models).
### 6) Are best-of-N and self-evolving tested? (user)
- They WERE (legacy v145/v146/v147/v148/v205) but were NOT in the battery.
- NEW `tests/v280_bestofn_selfevolve.py` (28): best-of-N N selection + ranker, and
  the self-evolving mine -> draft -> synth -> verify -> promote write-gate
  (fail-closed). Now enforced by the gate.
### Verified
- battery -> **46/46 GREEN** (added v280 + v281); py_compile clean.
- Browser (chrome-devtools, page 16): 0 console errors; model popover above the
  button + opaque; Browser copy-button shows "(2)"; terminal persists cwd through
  the UI; Settings->Models shows the context_length hint + the Thinking-effort card.

---

## JAG-282 — composer toolbar layout + editor tab path/copy-path (2026-10-04)
### 1) Composer toolbar looked broken (user: "che schifo questo format col bottone")
- The bar wrapped onto a second line (the model button was ~260px because of the
  "model: " prefix and a wide max-width) and the right-aligned bits landed oddly.
- Fix: the label is just the model name (`.mname`, ellipsised, max 190px); the bar
  is grouped into `.cb-left` (+ / queue) and `.cb-right` (model / mic / agent /
  stop / editor / send) with `margin-left:auto` on the right group. It is ONE row
  when there is room and WRAPS right-aligned when the column is narrow — it never
  clips. Placeholder shortened. Verified: all 8 controls on one visual row (same
  top), 0 clipped, at 773px and 1243px bar widths.
### 2) Editor tabs: where is the file? copy its path? (user)
- The open-file tabs showed only the basename; no way to know the full path, whether
  the file is inside the workspace, or to copy it. The FILE TREE already had a
  right-click menu (copy path / open / download) — the tabs did not.
- Fix: `renderTabs` sets `title` = full path, flags an OUTSIDE-the-workspace tab
  with a dashed border + ⚠ (and says so in the status bar), and wires
  `oncontextmenu` -> `showTabMenu` with: copy path, copy name, reveal in file tree,
  download, close. `revealInTree` opens the tree pane and flashes the matching row.
  `loadTree` now stores `state.root` so the workspace test is real.
- Verified live: the tab title is the full path; right-click shows the 5-item menu;
  "reveal in file tree" opens the pane and flashes the row.
### Verified
- NEW `tests/v282_composer_tabs.py` (12); battery -> **47/47 GREEN**.
- Browser (chrome-devtools, page 16): 0 console errors; composer one row + nothing
  clipped; tab menu + reveal work.

## JAG-283 — gradual zoom, clickable chat attachments, plan/dispatch coherence (2026-10-04)
### 1) Ctrl+zoom too coarse (user: "ctrl + fa zoom troppo marcato")
- Browser default Ctrl +/- jumps 10-20%. Replaced with an app-managed zoom: 5%
  steps (0.05) for Ctrl+= / Ctrl+- / Ctrl+wheel, Ctrl+0 resets to 100%, bounded
  0.7-1.6, level persisted in localStorage "sf_zoom" and re-applied on load.
- Verified live: 1 -> 1.05 -> 1.1 -> 1.05 -> reset ("").
### 2) Attachments were not clickable (user: "devo poterli aprire cliccandoci sopra")
- A file/image attached in the composer was only a label. Now every user bubble
  renders an ".attrow" of ".chatatt" chips: a file opens in the editor tab, an
  image opens in the existing image window, pasted text does nothing (toast).
  "_rawUrl(path)" -> "/api/fs/raw"; "_openAttachment" / "_bindAttachmentChips"
  (Enter/Space accessible). Attachments are kept in the transcript, so a reload
  re-linkifies any image path in the text as "imglink" (opens the image window).
- Verified live: chip datasource img:/text:; clicking opens the image window with
  the token URL; transcript image path -> imglink=1; 0 console errors.
### 3) TODOs appeared AFTER the answer, not marked done (user)
- Root cause (from the real transcript): the model did the work in prose, THEN
  called write_todos to author steps for the work it had just finished (e.g.
  "Osservare l'immagine allegata"), leaving them open. The harness was not
  injecting a "do not plan already-done work" rule strongly enough.
- Fix: TASK_POLICY gained a bullet - a step must describe work STILL TO DO, never
  author a step for something already finished in the turn; mark finished work
  'done' with evidence instead. The write_todos nudge now states the same and
  orders: mark already-done work done NOW, otherwise start with the FIRST open step.
### Verified
- NEW tests/v283_zoom_attachments.py (13); battery -> 48/48 GREEN.
- Browser (chrome-devtools): 0 console errors; zoom gradual; chips open the image
  window; transcript image path linkified.

## JAG-284 — approvals first, context cleanup, composer overflow menu, voice guidance (2026-10-04)
### 1) Approvals moved to the TOP of the inspector (user: "mettilo in alto")
- Approvals is now the FIRST inspector section (and first palette entry): it is the
  important HITL gate, so it must not be buried under Context.
### 2) Context "Other" category was always empty (user)
- The panel rendered a chip per category, so "Other" sat empty forever. Now only
  NON-empty categories render as chips; when nothing is carried the panel shows one
  hint line instead of empty chips + "nothing here".
### 3) Message-send bar still looked broken (user: "mi devi aggiustare la barra")
- Root cause: with the editor dock open the chat column is ~400px; 8 controls could
  not fit and wrapped into 3 messy rows. Secondary actions (editor / compact / new
  session) moved behind a "..." overflow menu; the right cluster is a single nowrap
  row and the model name absorbs the squeeze (shrinks, ellipsised).
- Verified live: wide -> 1 row; narrow (dock open) -> 2 tidy rows; 0 clipped; the
  overflow menu opens upward, closes on outside click, aria-expanded toggles.
### 4) Voice input - how other IDEs do it (user question)
- Answer baked into the in-GUI help: most IDEs rely on the OS dictation (Windows
  Win+H, macOS Fn Fn), which types into any focused field with no browser permission;
  browser tools use the Web Speech API, exposed only on HTTPS/localhost - the reason
  the mic is blocked on the plain-HTTP LAN origin (tunnel / flag fixes kept).
### Verified
- NEW tests/v284_ui_polish.py (12); battery -> 49/49 GREEN. Browser: 0 JS errors.

## JAG-285 — Orbit: a detachable beta console (src2/), multi-session, full Model Bay (2026-10-04)
### What and why (user)
- The stock /console "Model Bay" was fed from /api/status.models = the DGX router
  roster only, so every cloud / other-local provider was invisible; the deck was
  single-session and could not create sessions ahead of time. User asked for a
  coherent, OOP, DETACHABLE rebuild ("magari fai src2 ... possiamo sganciarla").
### Architecture (OOP, one concern per class)
- New package OUTSIDE the app: src2/orbit_beta/ - ModelBay (full providers.catalog),
  SessionRegistry (roster + pre-create), Orchestrator (dispatch a goal to N sessions
  in the background by draining server.chat_stream_gen), api.py (HTTP surface) and
  web/orbit.html (vanilla-JS classes). See src2/README.md.
- Server touches it through exactly two guarded hooks (_orbit_page before auth,
  _orbit_handle after auth) that call _orbit_module(); it returns None (swallowing
  try/except) when src2/ is absent, so the app is untouched if the beta is removed.
### Routes
- GET /orbit; GET /api/orbit/models|sessions|jobs; POST /api/orbit/sessions|dispatch.
### Verified
- NEW tests/v285_orbit_beta.py (20); battery -> 50/50 GREEN.
- LIVE on the DGX: /orbit 200; /api/orbit/models = 8 providers / 44 models
  (dgx, win, vllm, openrouter, deepseek, openai, anthropic, google); sessions 200.
- Browser: renders 8 providers / 44 models / 4 sessions, LED on; only the harmless
  favicon 401 (now suppressed), 0 real JS errors.

## JAG-286 — Orbit: board + "what needs me" inbox, modelled on Paperclip (2026-10-04)
### Why
- User pointed at the installed Paperclip repo (z:/Repositories/paperclip) as the
  reference ("scopiazzalo per bene"). Paperclip's signature surfaces: a board of work
  and ONE ranked inbox of everything that needs a human, typed by source and ranked
  by severity (services/attention.ts; pages/WhatNeedsMe.tsx).
### What
- src2/orbit_beta/attention.py — AttentionFeed: builds the ranked inbox from live
  SparkForge primitives: approval (approvals.list_all pending), failed_run (dispatch
  jobs in error), blocked_session (session stopped with open steps, taskgraph),
  budget_alert (context pct >= 90 via server.context_usage). Severities
  critical/high/medium/low; AttentionFeed.board() groups sessions into
  working / needs-you / idle.
- api.py: new GET /api/orbit/attention (inbox + board).
- web/orbit.html rewritten around a Board (Working / Needs you / Idle) and a
  "What needs me" inbox with inline approve/deny (POST /api/approvals/:id).
### Verified
- tests/v285_orbit_beta.py extended to 24 (attention + board + route). Battery 50/50.
- LIVE: /api/orbit/attention 200 -> 1 item (medium blocked_session);
  board {working:0, needs:1, idle:4}. Browser: 8 providers / 44 models, board
  0/1/4, inbox 1, 0 console messages.

## JAG-287 — Agents & Jobs (orchestration v1) — foundation (2026-10-04)
User decisions (scope delegated to the agent): session = AGENT (id AX, todos AX.TY);
the letter J is reserved for JOBS (higher-level objects that orchestrate several
agents); team = coordinator + worker; designated/persistent org agents; badge +
guarded delete; local models one-per-GPU; fix the taskgraph .tmp race.
Full plan + domain model: .agent/design-agents-jobs.md
### A — foundation (this commit)
- Session id renamed JX -> AX in the GUI (_todoid, sidebar badge, graph head);
  todos render AX.TY. Legacy v169 test updated to the new prefix.
- webui copy tidied: the two verbose help lines (approvals note + MCP note) were
  synthesised to one professional line each.
- The deck button (#deck-open) now opens /orbit (the beta), not the old /console.
- taskgraph._write_json: UNIQUE temp name per write (was a fixed ".tmp" that could
  collide between the turn worker, the background planner and the UI node endpoint
  -> FileNotFoundError / lost update). Mirrors the JAG-201 transcript fix.
### Concurrency findings (verified by reading the code)
- ThreadingHTTPServer + per-session _turn_lock => two agents run truly in parallel;
  the global locks are brief metadata sections, not turn mutexes. The real cross-agent
  limit is the local model router: two local models on the SAME GPU thrash VRAM.
  Policy: one heavy local model per GPU; the rest of the team uses cloud models.
### Next (B/C/D)
- B: src/sparkforge/agents.py + jobs.py + API; main-GUI badge + delete guard.
- C: Orbit GUI (orbital theme + Tactical Task Graph with AX.TY ids/relations + org
  chart + jobs board).
- D: per-agent budget, heartbeats/routines, decision queue.
### B — Agents & Jobs core (this commit)
- src/sparkforge/agents.py — AgentRegistry: designate/list/get/tree/release + guards.
  Agent = a session (id AX); reports_to builds the org chart; storage data/agents.json.
- src/sparkforge/jobs.py — JobRegistry: create/list/get/dispatch + waves(). A Job (JN)
  has a goal, a coordinator, member agents and deps (DAG). dispatch runs the
  coordinator (decompose) -> workers in dependency waves (parallel within a wave) ->
  coordinator aggregates, reusing server.chat_stream_gen so every turn is real+persisted.
- src/sparkforge/orchestration.py — HTTP /api/agents* + /api/jobs*, delegated from
  api_v02.handle (no new server hook). DELETE /api/agents/<sid> is refused (409) while
  the agent still manages reports.
- webui/index.html — sessions show the AX id + a hex org-agent badge; deleting an org
  agent takes an explicit extra confirm and is refused if it manages reports.
### Verified (B)
- NEW tests/v286_agents_jobs.py (26); battery 51/51 GREEN.
- LIVE: designate->A1, tree roots [A1], guards blocked False, create job->J1,
  release + delete OK.
### Next (C)
- Orbit GUI: restore the orbital theme + Tactical Task Graph (AX.TY ids + relations),
  org chart view and jobs board (create goal + coordinator + agents + deps, dispatch).
### C — Orbit GUI: tactical graph, org chart, jobs board (this commit)
- src2/orbit_beta/web/orbit.html rebuilt: Board (Working / Needs you / Idle), Model Bay,
  Tactical Task Graph (ported DAG layout; nodes labelled AX.TY with dependency links,
  colour by status; click a board card to load its graph), Org chart (reports_to tree),
  Jobs board (create goal + coordinator + agents + mode, run, live per-agent runs),
  What-needs-me inbox, Feed.
- Fixed: the rewrite dropped the #targets element while renderTargets still wrote to
  it -> an unhandled rejection on every refresh. Re-added the element + guarded the fn.
### Verified (C)
- v285 extended; battery 51/51 GREEN.
- Browser: 8 providers / 44 models; graph "A1 Jago_session" 26 nodes / 10 links
  (ids A1.TY); org "no designated agents yet"; jobs list; 0 console messages.
### D — Routines (heartbeats) + per-agent daily budget (this commit)
- src/sparkforge/routines.py — RoutineRegistry (list/get/create/delete/set_enabled/due/
  _mark/tick/_fire) + start_scheduler(interval) singleton daemon. A Routine binds an
  agent to a goal + cadence (every_seconds, MIN 30). tick() honours the per-agent daily
  budget: over budget -> skips and records state "budget-skip"; else spawns a _fire
  thread that runs one real turn via jobs._run_agent.
- src/sparkforge/agents.py — resolve(ref) by session id OR A-id, by_id(aid),
  charge(ref) (daily budget; 0/absent = unlimited; day-rollover reset; False when
  exhausted). designate(...) gained daily_budget.
- src/sparkforge/orchestration.py — /api/routines* (GET list/one, POST create/tick/
  enable/disable, DELETE). server.py starts the scheduler after service.start (guarded).
- src2/orbit_beta/web/orbit.html — Routines panel (create: agent+goal+every; list with
  enable/disable/delete) + Api.del(); refresh() fetches /api/routines in parallel.
### Verified (D)
- NEW tests/v287_routines_budget.py (20); battery 52/52 GREEN.
- LIVE (service restarted): designate session->agent A2; create routine R1
  (next_run_in 60); list count 1; tick fired [] (nothing due); delete 200; cleanup ok.
### Next (all planned chunks A/B/C/D committed)
- Candidates for a future pass: Paperclip-style decision queue; routine run history.
### E — Decision queue (Paperclip parity) (this commit, JAG-288)
- src2/orbit_beta/decisions.py — DecisionQueue wrapping the attention feed: every
  item can be resolved inline. approve/deny delegate to approvals.decide; retry
  re-dispatches a failed background run; dismiss is a persisted ack so the inbox
  drains. The ONLY state kept here is the dismissed-id set (data/orbit_decisions.json).
- src2/orbit_beta/api.py — GET/POST /api/orbit/decisions; _retry_run re-dispatches an
  orchestrator run by its job key (falls through as "run not found" otherwise).
- src2/orbit_beta/web/orbit.html — AttentionView is now the "Decision queue": per item
  approve/deny (approvals), retry (failed runs), dismiss (always); all resolve through
  /api/orbit/decisions; refresh() reads the queue (carries the board too).
### Verified (E)
- NEW tests/v288_decisions.py (21); v285 assertion updated to the decisions endpoint;
  battery 53/53 GREEN.
- LIVE (service restarted): GET /api/orbit/decisions -> count 1, board 0/1/4;
  POST dismiss -> ok. Browser: "decision queue — 1 med", dismiss button, 0 console errors.
### F — Job ops + coordinator prompts (JAG-289)
- ROOT CAUSE (found by a real end-to-end run, not a unit test): the COORDINATOR
  prompt only said "decompose ... do NOT do the work yourself" and did NOT forbid
  tools/subagents, so the model spent a whole turn spawning subagents that timed out
  (~3 min each) — one job took >18 min before the workers even started.
- FIX (src/sparkforge/jobs.py): the coordinator DECOMPOSE turn, the worker turns and
  the AGGREGATE turn now explicitly say: reply in plain text, do NOT call tools, do
  NOT create/update a task list, do NOT spawn subagents. Decompose dropped from >18 min
  to ~7 s; workers now just deliver.
- FIX: JobRegistry.reconcile() — on startup (server.main) a job left "running" by a
  hard restart is closed as "error: interrupted by restart" (mirrors
  reconcile_orphan_turns for sessions). dispatch() now clears the stale error/ended.
- UI (src2/orbit_beta/web/orbit.html): the Org chart panel gained a "designate" form
  (session title + name + role + reports-to + model) — the WebUI could CREATE an org
  agent only via the API before. Jobs board now re-runs any non-running job.
### Verified (F)
- NEW tests/v289_job_ops.py (9); battery 54/54 GREEN.
- LIVE end-to-end (created agents + job through the Orbit WebUI):
  * 4 agents designated from the form: A3 Coordinator (orchestrator), A4 Researcher
    (analyst), A5 Modeler (api-designer), A6 Reviewer (reviewer), all reports_to A3.
  * Job J2 "Design a compact REST API for a personal library service" (coordinator
    mode, agents A3,A4,A5,A6) dispatched from the ▶ run button.
  * A3 decomposed the goal into one concrete assignment per agent in ~7 s.
  * A4 delivered a requirements report (~2.0 KB), A5 an endpoint/schema/error spec,
    A6 a review — all real model output (model nex-n25-mini-uncensored-q8).
  * Known slow point: the coordinator's AGGREGATE turn (large context, mini model)
    can take many minutes; a faster/stronger coordinator model is advisable.
### Next
- Consider a dedicated stronger coordinator model / a bounded aggregate (or stream the
  aggregate) so the final consolidated answer is produced quickly.
### G — GUI agent-id badge + composer anchoring (JAG-290, item 3+4)
- Item 4 (badge): the main GUI session badge and the todo prefix used the SESSION's
  internal sequence number (s.job) — so a designated agent showed "A7" while the job /
  coordinator referred to the real agent id "A3". Fix: `_agentNum(s)` returns the org
  agent's real number (from /api/agents) when the session is a designated agent, else
  the session sequence. Badge + `curJob` (todo prefix AX.TY) now agree with the job.
- Item 3 (composer): in a short / zoomed window the header wrapped to >150px and the
  send/stop row was pushed OUT of the frame. Fix: `#log{min-height:0}` (the log shrinks
  so the composer rises and stays anchored), `#composer{flex:0 0 auto}`, and a media
  query (@max-height 640 / @max-width 920) that keeps the header ONE scrollable row and
  lets the toolbar scroll instead of wrapping.
### Verified (G)
- Battery 54/54 GREEN (v286 assertion updated to the new badge).
- Browser (emulated 600x240): before -> composer 130px BELOW the frame; after -> 2px,
  composerBar visible. Badge now shows the real agent id.
- Item 0 (config, no code): the 4 org agents (A3-A6) set to model deepseek:deepseek-reasoner
  (agent record + session model) via trash/set_model.py.
### H — Orbit deck made dense + regrouped (JAG-291, item 1)
- Compiled CSS: tighter panels (10px gaps, 6px/10px headers, 8px padding), smaller
  scroll caps (26vh) and a 150px tactical graph.
- Regrouped the 3-column grid: (A) Board + Tactical Task Graph; (B) "New job" | "Command"
  side by side, then "Team models", then the Jobs list; (C) Org chart + Routines +
  Decision queue. Model Bay (was the 2nd panel, mostly noise) MOVED to a full-width
  bottom row next to the Feed (.wrap2).
- NEW "Team models" panel: one compact row per org agent with an LLM <select>, so each
  teammate's model is chosen right beside the Jobs panel (POST /api/agents {session,model}).
### Verified (H)
- Battery 54/54 GREEN; browser: 0 console errors; Team models shows 4 rows all on
  deepseek-reasoner; panels in the new order; .wrap2 present.
### I — Inter-job dependencies + org-chart cycle guard (JAG-292, item 2)
Item 2 = "copy the useful fundamentals from ruflo / paperclip": the two named
capabilities were the REPORTING system and jobs WAITING on sequential jobs.
- `jobs.py`: a job may now declare `blocked_by=[JN, ...]` (paperclip
  `issue_blockers` / ruflo `Task.resolveExecutionOrder`). It starts `blocked` and
  only a level-triggered `wake()` releases it — no busy poll. `wake()` is called at
  the end of every job `_run` (done AND error), releases each blocked job whose
  blockers are ALL `done` (status -> created + dispatch), and FAILS a dependent whose
  blocker ended in `error` ("dependency failed: Jn") so nothing deadlocks
  (paperclip: a cancelled blocker never unblocks). `dispatch()` refuses a blocked job
  (can_dispatch gate). `list()` normalises `blocked_by: []` for old jobs.
- `agents.py`: the org chart is now a validated forest. `designate(reports_to=...)`
  refuses a self-link or a cycle (`_reaches` walks the manager chain); new
  `chain_of_command(ref)` returns [agent, manager, ... root].
- API: `POST /api/jobs` forwards `blocked_by`; `POST /api/jobs/wake` sweeps on
  demand; `GET /api/agents/<sid>/chain` returns the chain of command.
- Orbit UI: the New-job form has a `blocked by` input (J ids, comma-separated); the
  Jobs list shows a `blocked` badge + a `⇤ Jn` "waits for" tag and hides ▶ run while
  blocked (`.st.blocked`).
### Verified (I)
- NEW tests/v290_job_deps.py 25/25; battery 55/55 GREEN.
- Live (service restarted): POST /api/jobs/wake -> {released:[],failed:[]};
  GET /api/jobs returns both jobs; GET /api/agents/tree roots=[A3] agents A3..A6.
### J — Orbit simplified: agents table + org chart + job-by-recipient (JAG-293, item: "togli tutto")
User: too many panels, too dispersive. Wanted: only a table of agents (creatable with
+, each with a model), the org-chart relations drawn as boxes, and the JOB (goal +
who you give it to, usually the coordinator). Plus the missing per-agent system
prompt + formal rules. Plus routines + feed kept.
- Frontend (`src2/orbit_beta/web/orbit.html`) REWRITTEN: 5 panels (Agents table,
  graphical Org chart, Job, Routines, Feed). Agents table = ID/Name/Role/Model/
  Reports-to/Brief/×, `＋ new agent` creates session+agent in one click, a running
  dot, and an inline ✎ brief editor (prompt + rules). Org chart = nested boxes +
  connector lines from `reports_to`. Job = goal + `assign to` (team auto = assignee +
  its direct reports). Removed: Board, Tactical Task Graph, Command, Team models,
  Model Bay, Decision queue.
- `agents.py`: designate stores `prompt` + `rules`; new `team_of(ref)` (self + direct
  reports) and `brief(rec)` (role + prompt + rules).
- `jobs.py`: `_run_agent` prepends the agent's brief to every turn (jobs AND routines
  share this path).
- `orchestration.py`: POST /api/agents forwards prompt/rules; POST /api/jobs derives
  the team + coordinator from `assignee`.
- Spec: `.agent/design-orbit-simple.md` (supersedes the UI section of the old spec).
### Verified (J)
- NEW tests/v291_orbit_simple.py 20/20; battery 56/56 GREEN.
- Live (service restarted, page reloaded): 0 console errors; agents table 4 rows;
  org chart 4 nodes (A3 root at y=416, A4–A6 at y=510, 98x62 boxes); 2 jobs listed.
- BUG found + fixed by the new id-guard test: JobsView.render referenced a missing
  `id="jobsCount"` -> Uncaught (in promise) killed the refresh. The v291 test now
  asserts every `$("id")` in the JS exists in the markup.
### K — Per-session ROLE.md: a role patch merged into the prompt (JAG-294)
From paperclip: role drives *which default instruction bundle* an agent gets, and the
agent prompt is a file bundle on disk **indexed by agent id** (`agents/<id>/.../AGENTS.md`),
composed as `canonical prompt + AGENTS.md`. Adapted to SparkForge:
- `roles.py`: ONE file per SESSION id (unique) so two agents sharing a folder never
  collide, stored OUTSIDE any workspace: `<SPARKFORGE_ROLES_DIR or repo>/data/roles/<sid>.md`.
  API: `path_for/key/read/write/delete`; an empty write clears (removes) the file.
- `prompt.py`: new DYNAMIC section `agent-role` (order 52, after the static front so
  cache-safety holds) whose provider renders the session's ROLE.md on top of the
  canonical prompt. It therefore applies to chat, jobs AND routines (`_system_prompt`).
  The content is ONLY the role + a few behaviour notes, never the whole prompt.
- `agents.py`: `brief()` and the `prompt`/`rules` record fields are GONE (superseded);
  `jobs._run_agent` no longer prepends anything (the section covers it). New
  `name_taken()` and designate now REFUSES a duplicate name (agents OR session titles);
  `team_of()` unchanged.
- API: `GET/POST/DELETE /api/roles?session=` (accepts a session id or an AX id).
- Orbit deck: the ✎ column edits the ROLE.md (fetches on open, POSTs on save).
- Primary WebUI: new inspector section **Role** (same API) — shared between both UIs.
- CLI: `forge roles show|set|clear|reset --session <sid|AX>` (set reads stdin/-),
  `forge agents ls|new|set|rm`, `forge jobs ls|new|run|wake`.
### Live test (mixed models, WebUI + CLI)
- CLI: `agents ls`, `roles set/show` (by AX -> resolved session), per-agent models
  (A3 `dgx:nex-n25-mini-uncensored-q8`, A4 `win:nex-n2.5-mini-uncensored-iq4xs`,
  A5/A6 `deepseek:deepseek-reasoner`), duplicate name REFUSED (exit 1), new agent OK.
- Orbit page: agents table shows the 5 agents with the exact models; org chart ok;
  the ✎ opens and loads A3's ROLE.md; 0 console errors.
- Primary WebUI: the Role section loads `data/roles/<A3 session>.md` on session select.
- Job J3 (assignee A3 -> team A3+A4+A5+A6) created + dispatched from the CLI.
### Verified
- NEW tests/v292_roles.py 23/23; v291 updated (team_of + simplified page); battery
  57/57 GREEN (battery exports SPARKFORGE_ROLES_DIR).
### L — Orbit tactical view, prompt window, main-app link, HITL replay (JAG-295)
Four operator-reported issues, all traced to a root cause and fixed:

1. Org box -> tactical view. Clicking an agent in the Orbit organigram now opens a
   modal (`#tacModal`) with the agent's task graph (`/api/sessions/<sid>/graph`),
   rendered as SVG nodes labelled `AX.TY` + `.glink` dependency edges. The simplified
   deck had dropped the tactical view; it is reinstated as an on-demand modal driven
   by `OrgChartView(onPick)` + the new `TacticalView` class.
2. Prompt window size + wording. The per-agent role textarea was tiny; `table.at
   tr.brief textarea` is now `min-height:190px` (measured live: 190px). The guidance
   text states it is the SAME `ROLE.md` edited in the main app (Inspector § Role),
   merged into the system prompt, never replacing it.
3. "main app" link auth error. The header link `/` did not carry the token, so the
   main SPA loaded unauthenticated (401, JS never initialised). Fixed in `start()`:
   the link gets `/?token=<api.token>`. Verified: href `/?token=...`.
4. Invisible HUMAN IN THE LOOP form. TWO independent root causes:
   - RC-A (gate): `need_input` fired even on a HEADLESS autonomous turn (a JOB/routine
     has nobody to answer), so the coordinator replied "⏸ In pausa … vedi la card".
     New pure helper `keepgoing.hitl_gate(reason, open, autonomous)`: gate only when
     there are open steps, the stop is real (not `user_pivot`) AND a human is present.
   - RC-B (replay): the card was rendered ONLY from the live SSE event and was never
     rebuilt on reload. The persisted meta now carries `hitl_open` (the replayable
     payload) so `loadHistory` rebuilds the card.
   - BUG found while verifying: `append_message` merges meta FLAT into the message
     (`msg.update(meta)`), but the WebUI read a NESTED `m.meta.hitl` -> the rebuild
     never fired. Fixed to read top-level `m.hitl` / `m.hitl_open`; the test now locks
     the flat contract.

### Verified (live, no guessing)
- battery 58/58 GREEN; tests/v293_hitl.py 14/14 (incl. flat-meta + no-nested guards).
- Orbit: 5 org nodes (A3..A7); clicking A3 opens the tactical modal with 9 SVG nodes
  ("A3 Coordinator"); role textarea computed height 190px; main-app href carries token.
- Primary WebUI: reloaded with token, selected `coord-session` (`d813720c6eac`), and a
  REAL historical HITL message (`hitl:true, reason:"no_progress"`) now rebuilds the
  card from history (1 card, 4 action buttons) — previously 0.
### M — Orbit Constellation window + main-app deep-link (JAG-296)
Replaces the tactical modal with ONE floating, NON-modal constellation window and makes
Orbit a launchpad into the main app. Design: `.agent/design-constellation.md`; plan:
`.agent/plan-constellation.md` (both committed).

- Backend: `orbit_beta.api._constellation()` + `GET /api/orbit/constellation` aggregate
  `{agents, jobs, graphs}` in one read-only call (agents.REGISTRY.list, jobs.JOBS.list,
  taskgraph.load per agent session).
- Orbit UI: `Constellation` class replaces `TacticalView`/`#tacModal`:
  * floating `.cwin` (drag by titlebar, resize by corner grip, minimize, close), NO
    backdrop — the page behind stays interactive;
  * AGENT / ALL toggle; AGENT = the focused agent's task constellation (deps + subtasks);
  * ALL = one cluster PER AGENT (each agent once) + JOB pills above (amber) with thick
    `blocked_by` job→job edges and dashed job→agent "assigns" edges;
  * task colors by status (done/doing/todo/blocked/superseded|cancelled); legend in the
    detail strip;
  * a task: click = chat-extract popover (label/status/agent/evidence/reason + the last
    chat lines for that node from `/api/history` filtered by `m.node`), double-click =
    open the exact task in the main app (same tab).
- Deep-links: OrgChartView box dblclick and JobsView row dblclick open the agent's session
  in the main app; a task dblclick opens `/?token=..&session=<sid>&node=<nid>`.
- Main app (`webui/index.html`): `ensureToken()` now reads `?session=` (sets+persists the
  session) and stashes `?node=`; `loadHistory()` applies it once via `_scrollToNode`.

### Object model (confirmed with the operator)
Three types, five relations — JOB `JN` (blocked_by→JOB), AGENT `AX`=1:1 session
(reports_to→AGENT), TASK `AX.TY` (deps→TASK, same agent). A job assigns agents; tasks
live in the AGENT's session. The same agent may serve several jobs ⇒ its task list is
persistent/shared ⇒ the ALL view clusters per AGENT, not per job.

### Verified (live, chrome-devtools)
- Orbit: 5 org nodes; click opens the window (no backdrop); AGENT mode 9 nodes; ALL mode
  5 agent rects + 3 job pills; drag (left 100→240), resize (780x470→880x550); task click
  pops the extract with readable evidence + chat lines; popover cleared on mode toggle;
  0 console errors.
- Main app: `?session=d813720c6eac&node=n1` selects the session, renders the log, and
  `_scrollToNode('n1')` returns true (the section flashed); 0 console errors.
- battery 59/59 GREEN; tests/v294_constellation.py 13/13; v293 updated to the new window.
### N — Orbit: constellation docked + page reorganized + clearer job links (JAG-297)
Operator feedback on JAG-296: put the tactical view in the page (not floating), reorganize,
and make the job links readable.

- The floating `.cwin` window is GONE. The Constellation is now a **docked panel** in the
  page grid. New Orbit layout: **AGENTS (compact) | JOB** on top, then **ORG CHART |
  CONSTELLATION** side by side, then **ROUTINES | FEED**. Grid variants `.grid2.ab/.oc/.rf`;
  the ≤1000px media query collapses to one column.
- AGENTS is more compact (td padding, nowrap buttons) so JOB fits on its right; the role
  editor column is labelled **Role.md**.
- Constellation rendering rewritten:
  * `_shape()` computes dependency depth columns + the longest column, so each cluster box
    is **sized to FIT its nodes** (no overflow — verified 0 out-of-box nodes);
  * the SVG `viewBox` is the **content bounding box** (+ `preserveAspectRatio="meet"`), so
    everything is always visible however many agents/tasks there are;
  * clusters are packed by row (TARGETW wrap) so a wide ALL view stays tidy;
  * **directed arrows** via `<marker>`: thick `mJob` for job→job `blocked_by` (labelled
    `Jx→Jy`), dashed `mAsg` for job→agent "assigns", dashed `mDep` for task `deps`;
  * a legend strip under the panel (status colours + edge types);
  * click a task = chat-extract popover, double-click = open the exact task in the main app;
    a click on an org-chart box now just sets the AGENT focus (no window to open).
- The 5s refresh redraws the panel, but never while a chat-extract popover is open.

### Verified (live, chrome-devtools @1680px)
- layout: `.grid2.ab = 656|423`, `.oc = 432|648`, `.rf = 540|540` (2 columns each);
- no floating `.cwin`; AGENT mode = 9 nodes for A3; ALL mode = 5 agent clusters + 3 job
  pills + 3 arrow markers; **0 nodes overflow** their cluster; clicking the A4 org box
  switches focus to "A4 Researcher · 5 task(s)"; task click opens the extract popover;
  **0 console errors**.
- battery 59/59 GREEN; v294 16/16 (now asserts the docked panel + grid + markers);
  v293/v291 updated and green.
- **JAG-298** Bug-hunt WebUI + backend (uso estensivo dal vivo + analisi statica su
  tutto il frontend e il server). **10 bug reali trovati e corretti**, ognuno verificato:
  1. **`copyText` shadowing (WebUI)** — due `function copyText` nello stesso `<script>`;
     per hoisting la 2-arg (bottone copia messaggio, JAG-55) veniva sovrascritta dalla
     1-arg (JAG-279) → il bottone copiava `[object HTMLButtonElement]`. Fix: 2-arg
     rinominata `copyBtn` + 2 call-site. **Verificato dal vivo** (clipboard stubbato →
     copia il testo reale).
  2. **Orbit: poll 5s cancellava gli edit** — `AgentsView.render` rifaceva
     `#agBody.innerHTML` a ogni refresh → wipe di nome/ruolo/ROLE.md in corso. Fix:
     salta il rebuild se un INPUT/TEXTAREA in `#agBody` è focalizzato o il textarea
     ROLE.md è dirty. **Verificato dal vivo** (edit `ZZ_TEST_EDIT` preservato dopo 6.5s).
  3. **console.html: Event Stream mai popolato** — `/api/feed` emette eventi NOMINATI
     (`event: chat.run` …) ma la deck usava `es.onmessage` (tipo `message` di default)
     → mai chiamato; EVT/s fermo a 0. Fix: listener nominati + frame `backlog`.
     **Verificato dal vivo** (feed 200 righe, EVT/s > 0).
  4. **`/api/feed` riproduceva TUTTO il log durabile** — 1.120.023 righe in `data/events.db`:
     frame `backlog` di centinaia di MB → la console si BLOCCAVA (main thread fermo) e
     index.html iterava 1.1M eventi a ogni load. Fix: `events_since(last_id, limit)` con
     LIMIT SQL (subquery), `feed_gen` passa `FEED_REPLAY_MAX=300`. Client: `slice(-200)`.
  5. **editor.js** — `closeTab` sceglieva la tab attiva sbagliata chiudendo una tab PRIMA
     di quella attiva (fix: decrementa); `refreshAll` ora chiede conferma se ci sono edit
     non salvati (prima li scartava in silenzio).
  6. **XSS in `renderTools`** — nome/descrizione dei tool (anche da MCP esterni)
     interpolati senza `esc()` in testo E attributi. Fix: `esc()` su tutti i sink.
  7. **`loadApprovals`** (poll ogni 4s) senza try/catch → rejection non gestite. Fix: guard.
  8. **Orbit POST sempre HTTP 200** — `{"ok": false}` non mappato. Fix: helper `_ok` → 400.
  9. **`publish` contract envelope** — il rename `id`→`id_id` era DOPO l'INSERT: il replay
     da SQLite (`{**json.loads(data)}`) sovrascriveva l'`id` intero dell'envelope con quello
     del payload. Fix: rename PRIMA dell'INSERT (store e feed ora coerenti).
  10. **DoS upload raw** — `/api/voice/stt` e `/api/skills/install` leggevano il
      Content-Length illimitato. Fix: `min(n, MAX_BODY_BYTES)`.
  Suite `tests/v295_bugfix.py` (22/22) aggiunta al gate → battery **60/60 GREEN**.
  Restart servizio ok. Live: main console pulita (0 error/warn), copy OK, Orbit edit
  preservato, console feed popolato, pagine responsive.
  *(Non toccato: `graph_post` 200+null su nodo ignoto, `_TURN_LOCKS` non limitato,
  `STORE_LOCK` morto — minori, valutati a basso impatto/rischio.)*
- **JAG-299** Coerenza JOB↔TODO + round-2 di bug-hunt (analisi richiesta dall'utente
  sulla confusione J2/J3 nel coordinator). **Causa radice trovata e corretta:**
  1. **I job condividevano il task-graph degli agenti**: J2 e J3 girano sugli STESSI
     agenti (A3,A4,A5,A6); il graph è persistente per sessione, quindi i todo aperti
     di J2 (`n1..n5`, "personal library API") restavano "correnti" mentre l'agente
     lavorava J3 ("HTTP caching") → la card HUMAN-IN-THE-LOOP scattava sui todo di
     J2 e il modello entrava in confusione (reasoning: "no replan tool… user says do
     not create/update task list… must do one"). Fix: `jobs._scope_graph()` — ogni
     dispatch di job apre un **nuovo plan** sul graph dell'agente e lo tagga con il
     `jid` (JN). Così i todo di un job non sconfinano nel successivo.
  2. **Contraddizione nei messaggi job**: il turno è `autonomous=True` →
     `assemble_turn` antepone "AUTONOMOUS GOAL MODE — FIRST emit write_todos", mentre
     il messaggio job diceva "do NOT create or update a task list". Rimosso il divieto
     (combatteva l'harness): ora il piano del job è coerente e **tracciato per job**.
  3. **Ogni nodo porta `jid`** (`taskgraph.add_node`) e la UI lo mostra: header del
     cluster nella costellazione ("A4 Researcher · J3") e tag sul todo nel main app
     (`_nodeJob` → "J3 · A4.T1 · J2" distingue i job a colpo d'occhio).
  **Round-2 bug-hunt (altri 3 bug reali corretti):**
  4. **Race `_ACTIVE_CHAT`** (server): il turno 1, uscendo, cancellava la registrazione
     del turno 2 (che era in coda sul lock) → `/api/chat/live` diceva "idle" e
     `/api/chat/attach` non riagganciava un turno ancora vivo. Fix: token per-turno,
     pop condizionale (`tok is _turn_tok`).
  5. **console.html**: l'abort in modalità demo non fermava l'intervallo di "digitazione"
     finta (`endTurn` non lo clearava) → i pixel continuavano dopo Abort. Fix: clear in
     `endTurn`.
  6. **editor.js**: l'albero file è session-scoped (`?session=`) ma read/write/raw NO →
     l'editor apriva/salvava nel workspace DEFAULT invece che in quello della sessione
     (e poteva rifiutare un file appena elencato). Fix: `sessionQS()`/`SESSION()` su
     read/raw/write.
  Suite `tests/v296_job_todos.py` (16/16) + `tests/v297_round2.py` (7/7) nel gate →
  battery **62/62 GREEN**. Restart ok. Live: Orbit ALL mode 5 cluster/20 nodi, main e
  console pulite (0 error/warn).
  *(Nota Q1: la sessione A4 "research" NON è tecnicamente failed — J3 A4 = `done`. Il
  "failed" percepito è il piano/todo rimasti aperti e attribuiti a J2. Il testo
  "HTTP caching lets clients and intermediaries reuse stored responses…" è la risposta
  del coordinator A3 a J3, replicata (parafrasata) da A4/A5/A6 — comportamento
  voluto: ogni agente risponde alla propria assegnazione.)*
- **JAG-300** Ottimizzazione (skill `performance-optimization`: misura → fix → ri-misura).
  **Misurato prima:** `events.db` = **1.120.026 righe / 159 MB** (~95% delta di
  streaming: `chat.delta` 880k + `agent.think` 190k); `publish()` (1 riga per token)
  = **6,028 ms/call**; l'unico endpoint lento era `/api/orbit/attention` ~44-55 ms.
  1. **WAL + `synchronous=NORMAL`** su `db()` (`PRAGMA journal_mode=WAL`,
     `PRAGMA synchronous=NORMAL`): il log è write-heavy e di sola replay, non serve
     il fsync a ogni delta. **Ri-misurato: `publish()` 6,028 → 0,033 ms/call (~183×)**;
     live dopo restart **0,027 ms/call**.
  2. **Retention del log** (crescita illimitata = 159 MB e in salita): costanti
     `EVENTS_KEEP=200000`, `PRUNE_INTERVAL_S=900`, `PRUNE_BATCH=50000`,
     `prune_events(keep=)` (DELETE a batch sotto `_db_lock`) + `_start_event_pruning()`
     (thread daemon) avviato in `main()`. **Live: righe 1.120.026 → 200.000**; le
     pagine liberate restano nel freelist (28.239) e vengono riusate (nessun VACUUM
     automatico: costo I/O evitato di proposito).
  3. **Bug reale – Orbit `_budget`** (`attention.py`): chiamava
     `context_usage(sid)` **senza modello** → `context_budget(None)` = budget DEFAULT,
     non la finestra del modello della sessione. Una sessione su un modello
     small-window leggeva un `pct` falsamente basso → l'alert di budget non sarebbe
     mai scattato (regressione del fix JAG-258, che altrove fa
     `context_budget(resolve_ctx_model(sess))`). Fix: `context_usage(sid,
     model=resolve_ctx_model(s))`.
  4. **Doppia lettura del roster** per poll: `snapshot()` chiamava `registry.list()`
     e l'handler `api.py` la richiamava per il `board`. Fix: `snapshot(sessions=None)`
     accetta il roster già calcolato; l'handler lo passa una sola volta.
  Suite `tests/v298_perf.py` (**18/18**) nel gate → battery **63/63 GREEN**.
  Live `/api/orbit/attention` **55 → 36 ms**; tutti gli altri endpoint ≤7 ms;
  restart ok. Evidenza: `trash/perf_probe.py`, `trash/bench_publish.py`.
- **JAG-301** Bug-hunt mirato su attribuzione job↔todo + coerenza Orbit (continuazione
  autonoma). Audit: moduli `orbit_beta` (bay/decisions/orchestrator), `jobs.py`,
  `taskgraph.py`, e audit LIVE del WebUI (main/console/orbit) via chrome-devtools →
  **0 errori console, tutte le richieste 200** (restano solo i notice DOM beningni).
  1. **Bug reale — tag job "stantio" sui todo manuali** (`server.py`): il `jid` era
     scritto sul graph della SESSIONE da `_scope_graph` (job) ma **mai azzerato**.
     Dopo un job J3, un turno MANUALE sulla stessa sessione crea todo che ereditano
     `jid="J3"` → la UI li etichetta come appartenenti a J3 sebbene non lo siano (la
     **stessa confusione J2/J3** già segnalata). Fix: il `jid` è ora **per-turno** —
     `chat_stream_gen(..., jid=None)` lo scrive sul graph a inizio turno (i job
     passano il loro `jid`, i turni manuali passano `None` e azzerano il tag); anche
     il path non-streaming `/api/chat` azzera il tag.
  2. **Doppia lettura del roster** anche in `decisions.queue()` (stesso pattern di
     `/api/orbit/attention` corretto in JAG-300): ora calcola il roster una volta e
     lo passa a `snapshot(sessions)`.
  Nota: `/api/orbit/attention` e `/api/orbit/decisions` sono **API esposte ma non più
  chiamate** dalla pagina Orbit semplificata (v291) — restano corrette e testate.
  Suite aggiornate: `v296_job_todos` (22/22, +6 check), `v298_perf` (19/19),
  `v288_decisions` (fix dello stub FakeFeed) → battery **63/63 GREEN**. Restart ok,
  tutti gli endpoint 200, log eventi stabile a 200k righe.
- **JAG-302** Bug-hunt: leak di memoria per-sessione (seguito di JAG-179, che aveva
  ripulito solo i FILE). Le mappe in memoria con chiave = session id non venivano MAI
  potate, quindi crescevano a ogni ciclo crea/chat/cancella:
  1. **`STEER_INBOX`** — `drain_steer` ri-INSERIVA una lista vuota a ogni iterazione
     (`STEER_INBOX[sess_id] = []`), lasciando una voce permanente per ogni sessione
     che avesse mai girato un turno. Fix: `return STEER_INBOX.pop(sess_id, [])`
     (stesso valore di ritorno, nessuna voce creata).
  2. **`_forget_session_runtime(sid)`** nuovo: alla DELETE di una sessione ripulisce
     `_REAL_PROMPT_TOKENS`, `_REAL_CACHED_TOKENS`, `_TURN_LOCKS`, `STEER_INBOX`,
     `_ACTIVE_CHAT` e — se nessun turno è vivo — anche `ABORT_INBOX`. Se un turno È
     vivo il flag di abort resta (il turno in corso deve ancora vederlo per fermarsi).
     Wireato nella route `DELETE /api/sessions/<sid>` subito dopo `_purge_session_artifacts`.
  3. **`ABORT_INBOX`**: cancellare una sessione IDLE vi lasciava per sempre l'id
     (la flag veniva azzerata solo a fine turno). Ora la DELETE la ripulisce se idle.
  Suite nuova `tests/v302_runtime_leak.py` (**16/16**) nel gate → battery **64/64 GREEN**.
  Live end-to-end: crea sessione usa-e-getta → presente → `DELETE` (200, `ok:true`,
  `removed:[...json]`) → assente. Restart ok, tutti gli endpoint 200.
- **JAG-303** Job coordinato end-to-end (richiesta utente: "give job to a coordinator he
  will automatically delegate parts to subagents… check monitor all and fix anything").
  Guidato la skill `systematic-debugging` (root cause prima dei fix). Eseguito il job
  complesso **J2** (goal: progettare una REST API, coordinator A3 + team A4/A5/A6) e
  monitorato tutto il flusso (API `/api/jobs`, eventi, transcript degli agenti, grafo).
  **Il coordinatore DELEGA automaticamente** al team che conosce (genera un bullet per
  agente: A3/A4/A5/A6). Trovati e corretti **3 bug reali**:
  1. **Ogni worker riceveva l'INTERO piano** come "Your assignment" (tutti e 4 i bullet,
     anche quelli degli altri) → i worker non sapevano quale parte fosse la loro e
     rifacevano il lavoro degli altri (evidenza: A4/A6 producono l'intera specifica;
     conflitti tipo `author` string vs `authors` array). Fix: `_assignment_for(plan, aid)`
     estrae la RIGA del worker (fallback al piano intero se non nominato) e il messaggio
     ora dice "Your assignment (yours only)… do NOT do the other agents' parts".
     Live: A4/A5/A6 ricevono solo la propria riga (920/2062/1158 char, in-lane).
  2. **`_run_agent` restituiva la LAST assistant message** = un riassunto di 251 char
     invece del deliverable. Causa: a fine turno l'harness inietta "report the RESULT you
     already have" e il modello risponde con un riepilogo, DOPO aver già prodotto il
     deliverable (4688 char) in un messaggio precedente. Fix: `_best_reply(messages)` →
     il messaggio assistant PIÙ SOSTANZIOSO del turno (con boundary `before`), non l'ultimo.
     Live: J2 A3 finale = **5468 char** = deliverable completo (endpoints+schema+errori+esempi).
  3. **Loop keepgoing nel turno di sintesi**: i todo di decomposizione del coordinatore
     (`n10..n13`, "Assign A4 to …") restavano APERTI sul grafo di A3, quindi l'harness
     iniettava "you left 4 task(s) OPEN" (`plan.continuing`+`harness.inject pivot`) e il
     coordinatore restava a gestire la lista invece di scrivere il deliverable. Fix:
     `_close_open_todos(sid)` chiude i nodi aperti del plan corrente prima della sintesi
     (il team ha già girato). Live: "ALL OPEN nodes = 0" prima della sintesi, nessun loop.
  **Verifica finale 100%** (J2 rieseguito dopo i fix): coordinator delega al team; ogni
  worker resta nel suo ambito; A3 = 5468 char con TUTTI e 4 i deliverable (endpoints/schema/
  errori/esempi) → `status=done`, `error=''`. Suite nuova `tests/v303_job_delegation.py`
  (**28/28**) nel gate → battery **65/65 GREEN**. (Prima dei fix il job finiva con un
  riassunto di 251 char e, dopo i primi due fix, entrava in loop keepgoing.)
- **JAG-304** Il harness accetta come RISPOSTA l'artefatto JSON del modello (seguito di
  JAG-303). Monitorando il 2° run di J2 negli eventi del DB ho trovato un 4° bug reale,
  piu' sottile: il coordinatore A3 (sessione `d813720c6eac`) consegnava il PROPRIO
  deliverable come JSON — un JSON-Schema `Book` e una envelope di lista
  `{"items":[],"pagination":{...},"links":{...}}` — e il loop chat lo RIFIUTAVA come
  "azione non valida" (`harness.inject retry: "That was not a valid action..."`, 3 volte
  nel run). Causa: il ramo "stray JSON" trattava QUALSIASI dict JSON parsato come un
  tentativo di azione malformata, anche quando non conteneva alcuna chiave d'azione.
  Effetto: retry inutili e, a 4 di fila, stop prematuro del turno (`plan.no_valid_action`)
  — la stessa classe di guasti di #2/#3 che abbassa la qualita' del job.
  Root cause (evidenza): eventi `id=1131782/1132405/1132407` = inject retry con lo
  schema/envelope citati. Fix:
  1. nuovo `_looks_like_action_dict(act)`: un dict e' un TENTATIVO d'azione solo se ha
     una chiave top-level fra `action/tool/tool_name/args/todos/steps` (segnali d'azione)
     oppure un arg-grezzo `command/path/content/url/query/pattern`. Un dict SENZA queste
     chiavi e' un ARTEFATTO = la RISPOSTA del modello (schema, envelope, record).
  2. nel ramo stray: se `not _looks_like_action_dict(act)` → `final_answer = answer` +
     stream + `break` (l'artefatto si mostra), invece del retry "not a valid action".
  3. flag `_final_is_artifact` che esenta un artefatto confermato dal guard di coda
     (`_looks_like_json_action(content)`) — cosi' uno schema che per caso contiene la
     sottostringa "action"/"tool"/"args" non viene comunque svuotato.
  Verifica: suite nuova `tests/v304_json_artifact.py` (**21/21**) nel gate → battery
  **66/66 GREEN**. J2 rieseguito con il fix live: nessun retry "not a valid action",
  coordinatore A3 = deliverable completo, `status=done`, `error=''`.
- **JAG-305** Budget di output: il deliverable lungo non va piu' troncato (seguito di
  JAG-303/304). Dopo aver ri-eseguito J2 con il fix JAG-304 (0 retry spuri confermati),
  il job risultava `done` ma il deliverable finale di A3 era di soli **3234 char e
  TRONCATO** a meta' tabella (mancava la sezione 4, gli esempi). Root cause (evidenza,
  NON un'ipotesi): `data/events.db` event `id=1135308` run.metrics del turno di sintesi:
  `completion_tokens: 4096` ESATTI, `stop_reason: null`, `think_chars: 12103`. Il router
  llama.cpp (`:8080`) applica un default di **4096 token** per completion quando la
  richiesta NON manda `max_tokens` — e l'harness non lo mandava (`SPARKFORGE_MAX_TOKENS`
  default `0` = omesso). Un modello di reasoning spende gran parte di quel budget nel
  suo "thinking" (12k char), quindi la RISPOSTA viene tagliata. NON era colpa di JAG-304:
  era un bug preesistente, che i retry spuri di prima MASCHERAVANO (ogni retry
  rigenerava la risposta e `_best_reply` teneva la piu' lunga/completa).
  Verifica empirica: probe `trash/tok_probe.py` → il router ONORA un cap esplicito
  (`max_tokens=6000` → `completion_tokens: 5044`, `finish_reason: stop`). Fix:
  `MAX_TOKENS` default `"0"` → `"16384"` (generoso ma limitato; `0` = comportamento
  vecchio, ossia ometti e lascia decidere al router), ancora override via
  `SPARKFORGE_MAX_TOKENS`. Suite nuova `tests/v305_output_budget.py` (**7/7**) → battery
  **67/67 GREEN**.
  Run di verifica finale (entrambi i fix live): A3 = **5451 char, COMPLETO** (sezione 1
  Endpoints, 2 Book JSON Schema, 3 Standard Error Payload, 4 Request Examples con un
  esempio per OGNI endpoint List/Create/Retrieve/Update/Soft-archive), `status=done`,
  `error=''`, **0** retry "not a valid action", 0 graph.error/job.error. Nota ONESTA: in
  QUEL run la completion ha usato 3325 token, sotto il vecchio cap 4096, quindi sarebbe
  stata completa anche senza il fix; JAG-305 e' la GARANZIA per il caso pesante (il run
  precedente aveva colpito esattamente 4096 e si era troncato). La fix e' comunque
  validata dal probe sul router e dal test v305.
- **JAG-306** Un job chiuso NON deve lasciare todo aperti (segnalazione utente: "vedo
  ancora molti todo non chiusi, come puoi dire che il job e' finito bene?"). Aveva
  ragione: dopo J2 il grafo del coordinatore A3 mostrava **6 todo APERTI**
  (`plan=7 n20..n25`) pur con `status=done`. Root cause (evidenza, `data/events.db`):
  `id=1136402..1136407` = il mio `_close_open_todos` (JAG-303) chiude il plan=6 PRIMA
  della sintesi; poi `id=1136789..1136800` = il turno di SINTESI genera un NUOVO plan
  (`plan=7 n20..n25`, `source=model:write_todos`, da `graph.generated goal="Team
  results:..."`) e produce il deliverable; il turno finisce (final_answer) SENZA chiudere
  quel plan. Il mio `_close_open_todos` girava solo PRIMA della sintesi → il plan creato
  DALLA sintesi restava aperto quando il job veniva marcato `done`. Non era colpa dei
  worker (A4/A5/A6: 0 aperti). Fix: `_close_job_todos(sessions)` (staticmethod) chiude i
  nodi aperti del plan corrente di OGNI agente del job e ne riporta il conteggio; chiamata
  in `_run` DOPO la sintesi e PRIMA di `status=done`, che ora registra `todos_closed`.
  Invariante imposta: **un job `done` ⇒ zero todo aperti in tutti i suoi agenti**.
  Suite `tests/v306_job_todos_close.py` (**17/17**): include un test di INTEGRAZIONE che
  guida la vera `_run` con un turno di sintesi che LASCIA un todo aperto → il sweep lo
  chiude e `todos_closed=1` (prova deterministica che il fix scatta). Battery **68/68
  GREEN**. Verifica live (J2 rieseguito): **tutti gli agenti a 0 todo aperti** a fine job
  (A3 plan=8, A4/A5/A6 a 0). Nota ONESTA: in QUEL run `todos_closed=0` perche' il modello
  non ha lasciato un plan di sintesi (e il close pre-sintesi aveva gia' ripulito il
  residuo del run precedente), quindi il run live conferma l'INVARIANTE ma il meccanismo
  del sweep e' provato dal test di integrazione.
- **JAG-307** L'UI contava gli stati CHIUSI come "aperti" (seguito della segnalazione
  utente: "vedo ancora molti todo non chiusi"). Anche dopo JAG-306 (che chiude i todo del
  job) lo stato VISIBILE restava sbagliato, per due bug di conteggio:
  1. **Deck** (`webui/console.html`, chip TASKS): contava come "open" OGNI nodo con
     `status !== "done"`, includendo `superseded`/`cancelled` — che sono CHIUSI. La
     sessione del coordinatore A3 (`22 done + 3 superseded`, **0 todo aperti**) mostrava
     quindi "**3 open / 25**" (evidenza: `/api/plan?session=d813720c6eac` →
     `counts={'done':22,'superseded':3}`). Fix: contare solo gli stati davvero aperti
     (`todo/doing/blocked`).
  2. **Pannello** (`webui/index.html`): `renderGraph` faceva `_pn.length ? _pn :
     graph.nodes` — quando il plan CORRENTE e' vuoto (il turno di sintesi apre e chiude un
     plan), ricadeva sull'UNIONE di TUTTI i plan, riesumando passi vecchi/chiusi; e la mappa
     `mark` non aveva `superseded`, che quindi rendeva "☐" (sembrava aperto). Fix: fallback
     all'ULTIMO plan che HA passi (mai l'unione) + `superseded:"⊘"`.
  Verifica: `node --check` sui due script inline = OK (nessun errore di sintassi). Suite
  `tests/v307_open_count.py` (marker) nel gate → battery **69/69 GREEN**. Dopo i fix: la
  sessione del job mostra **0 open**, il pannello mostra l'ultimo plan reale (tutti done).
- **JAG-308** ROOT CAUSE dei todo aperti dopo un job — e RITIRO del fix esterno JAG-306.
  L'utente: "non volevo che quel caso fosse chiuso a forza dall'esterno, ma che non si
  ripeta; l'harness+llm deve poter chiudere i todo da solo". Ricostruita la catena con
  EVIDENZE (`data/events.db` + codice), SENZA indovinare:
  1. **JAG-194** (`chat_stream_gen`, inizio turno): se il grafo e' `all_done` → `begin_plan`
     crea un plan NUOVO e VUOTO.
  2. **JAG-76** (fine turno): se il plan corrente non ha nodi, un **planner in background**
     (`start_run_graph`→`generate_from_model`) crea i todo **a partire dal MESSAGGIO del turno**.
  3. **JAG-173**: l'harness NON chiude mai un todo da solo (senza evidenza = mentire);
     **JAG-295**: un turno headless (job) non ha HITL gate → "il turno si ferma e i passi
     aperti restano nel grafo".
  Quindi nel turno di SINTESI: `_close_open_todos` (JAG-303) rende il grafo `all_done` →
  parte un plan vuoto → il fallback planner lo riempie coi todo del messaggio
  "Team results: ..." (eventi `1136789..1136801`, `graph.generated goal="Team results:..."`)
  → nessun turno li esegue, nessuno li chiude → job `done` con 6 todo APERTI. **Non e' un
  caso da forzare: e' l'harness che CREA todo che l'LLM non puo' chiudere.**
  FIX (root cause, non sintomo):
  a) nuovo `_should_autoplan(jid, graph, autonomous, message)` — il fallback planner NON
     gira MAI per un turno JOB (`jid` impostato): il grafo del job e' del job (il
     coordinatore decompone, i worker scrivono/chiudono i PROPRI todo). Resta attivo per i
     turni interattivi (il pannello 🧩 GRAPH non resta vuoto).
  b) **stesso bug di conteggio nel server**: `plan.incomplete` usava
     `status not in ("done","cancelled")` e contava i `superseded` (CHIUSI) come aperti →
     una sessione tutta chiusa riportava "3 open" e si ri-naggava al turno dopo. Ora usa
     `taskgraph.OPEN_STATUSES`. (Probe: grafo A3 = 25 nodi, OLD=3 aperti [superseded],
     NEW=0.)
  c) **RITIRATO il band-aid esterno JAG-306** (`_close_job_todos` + `todos_closed`): con la
     root cause corretta non serve piu' e l'utente l'aveva giustamente rifiutato.
  Suite `tests/v306_job_todos_close.py` riscritta (**11/11**): `_should_autoplan` False per
  ogni turno job, True per gli interattivi prosa-lunghi, False se il plan ha gia' passi; lock
  di sorgente su gate del fallback, conteggio `plan.incomplete` e rimozione del sweep.
  Battery **69/69 GREEN**.
  Verifica LIVE (J2 rieseguito col root fix, SENZA alcun sweep): eventi del coordinatore =
  solo `plan.stopped {reason:goal_reached, open:0}` — **nessun `graph.generated`** (il
  fallback planner non e' partito) e **nessun `graph.node.updated` con source=job** (nessuna
  chiusura esterna); tutti gli agenti A3/A4/A5/A6 a **0 todo aperti** a fine job. Il 0 e'
  quindi merito della root cause, non di una toppa.
- **JAG-309** — perché A3 mostrava un modello LOCALE in Orbit ma `deepseek-reasoner` nel
  composer (e "la GPU girava davvero"): **due campi `model` per la stessa entità, due
  scrittori, zero sincronizzazione.**
  Evidenza (`trash/model_probe.py`): A3 `agent.model=dgx:nex-n25-mini-uncensored-q8` ma
  `session.model=deepseek:deepseek-reasoner`; A4 idem; A5/A6 coincidono per caso; A7 `None`.
  Catena:
  1. un AGENTE È una SESSIONE (`agents.py`: `agent["session"] == sid`);
  2. **Orbit** scrive SOLO `agent["model"]` (`POST /api/agents` → `orchestration.py` →
     `designate()`, unica riga `a["model"] = ...`): i JOB leggono quel campo
     (`jobs.py` `roster.get(aid,{}).get("model")`) → girava il modello locale;
  3. il **composer** scrive/legge SOLO `session["model"]`
     (`POST /api/sessions/<id>/model`; `index.html` `currentModel()`) → mostrava deepseek.
  Non era "un caso da forzare": erano due verità parallele sulla stessa entità.
  FIX (root cause, policy scelta dall'utente: **UNIFICA SEMPRE**):
  a) nuovo `server._set_session_model(sid, model)` = **UNICO scrittore**: scrive la sessione
     E, se la sessione è un agente, anche l'agente. `""` azzera entrambi.
  b) `designate()` ora ha il contratto chiaro: `model=None` = non toccare, `""` = azzera
     (`if model is not None: a["model"] = (str(model)[:120] or None)`).
  c) `POST /api/agents` (Orbit) dopo `designate` sincronizza il modello di sessione (se
     `model` è assente, l'agente eredita quello della sessione → niente divergenza alla
     creazione). `POST /api/sessions/<id>/model` (composer) passa dall'unico scrittore.
  d) nuovo `server.reconcile_agent_models()` all'avvio (accanto a `backfill_*`): guarisce le
     divergenze legacy, **vince il modello dell'agente** (è ciò su cui i job hanno girato);
     idempotente.
  Suite `tests/v309_model_sync.py` (**21/21**). Battery **70/70 GREEN** (tally reso dinamico:
  non più "69/69" hardcoded). Verifica LIVE dopo `systemctl --user restart sparkforge.service`:
  A3 e A4 ora hanno `agent.model == session.model` (locale); A5/A6/A7 invariati; servizio
  `active`. Backup: `data/agents.json.bak-309`, `data/sessions.bak-309`.
- **JAG-310** — "il coordinator ha ricevuto un report ma non ha mai risposto / il sistema non
  riesce ad arrivare a una fine da solo". L'utente vedeva il messaggio iniettato
  **"Team results:"** come ULTIMA cosa nella sessione A3, senza alcuna risposta.
  Sul DISCO invece la risposta c'era: `chat.done session=d813720c6eac message_id=114
  think_chars=17541 error=false`, ultimo messaggio = assistant 5096 char, job J2 `done`,
  grafo tutti i nodi `done`. Quindi non era "il coordinatore non risponde": era un **buco di
  consegna** + un **buco di accettazione**. Due cause distinte, entrambe "il sistema finge
  di essere arrivato a un fine":
  1. **UI (consegna)** — `attachIfRunning(sessionId)` girava SOLO all'apertura/cambio sessione
     (`webui/index.html`), e il feed globale (`connectFeed`) su `chat.user` stampava solo una
     riga corta e su `chat.done` faceva solo `loadCtx()`. Un turno che PARTE su una sessione
     GIA' aperta ma non avviato da quel browser (turno JOB headless, o una routine) non veniva
     mai seguito: l'utente restava sul prompt "Team results" finche' non ricaricava a mano.
     FIX: il feed ora segue la sessione aperta (`attachIfRunning` su `chat.user` della sessione
     corrente → replay dal feed durevole + tail) e, su `chat.done` non-gia'-in-stream, tira la
     risposta persistita (`loadHistory/loadPlan/loadGraph`).
  2. **Accettazione** — `jobs._run_agent` ripiegava sull'ULTIMO messaggio assistant dell'INTERA
     sessione: se il turno non produceva nulla restituiva una risposta **STANTIA** di un run
     precedente, e `_run` marcava comunque `status=done`. Cosi' un job risultava "accettato"
     senza che il coordinatore avesse risposto. FIX: il fallback e' limitato a QUESTO turno
     (`turn = messages[before:]`), e `_run` ora **solleva** `"coordinator produced no final
     reply"` → il job va in `error` (visibile, ri-eseguibile) invece di essere accettato a vuoto.
  Suite `tests/v310_agent_turn_delivery.py` (**11/11**): fallback per-turno (stale→"" ; nuovo
  reply→suo ; il sostanziale vince), `_run` che RIFIUTA un coordinatore muto e ACCETTA uno che
  risponde, + lock di sorgente su index.html e jobs.py. Battery **71/71 GREEN**.
  Nota: per la parte UI serve **ricaricare il browser** (index.html statico); il lato Python e'
  attivo dopo `systemctl --user restart sparkforge.service` (fatto).

## 2026-10-06 — JAG-311 session controls + deep-debug sweep (commit 4c8d1ca)

Goal: finish the debug sweep, then ship session clear/rename, job delete,
zoom/pan and a theme pass. PUSH after.

Shipped (battery 72/72 GREEN, live HTTP smoke green):
- tests/ reorganised: tests/acceptance/ (auto-discovered by battery.sh),
  tests/legacy/, tests/live/, tests/nightly/, tests/properties/.
- Nightly mega loop (tests/nightly/mega.sh) ran on DGX; found the real bug
  `jobs.py` used `str(exc)` after ruff stripped `as exc` (bare except). Fixed
  by binding `_e`/`_err` and passing `_err=_err` into the lambda (late-binding).
- Deep-debug session (docs/research/2026-10-06-debugging-large-codebases.md)
  found & fixed: jobs NameError, swarm.py missing `import queue`,
  server.telemetry_summary missing `import subprocess`, keepgoing sha1->sha256,
  sandbox 0o777->0o755.
- Session CLEAR: POST /api/sessions/<sid>/clear (wipes messages + graph, keeps
  session/agent/role), published as session.cleared; wired in main rail menu,
  command palette, and Orbit agents row.
- Session RENAME: POST /api/sessions/<sid>/rename; wired in the rail menu.
- Session rail: dropped the folder icon; the X is replaced by a hover ⋮ menu
  (Pin/Unpin, Rename, Clear chat+tasks, Delete) sorted pinned-first.
- JOB DELETE: JobRegistry.delete (refused while running) + DELETE /api/jobs/<id>
  + Orbit job row ✕ button.
- Compaction notice: context.compact (origin=manual|auto) + context.auto_compact
  are pushed to the chat feed and reload history; NO transcript pollution.
- Constellation + org chart: wheel-zoom + drag-pan.
- Theme: refined slate palette (main + Orbit) + font smoothing.
- v311 acceptance test (29 checks) locks all of the above.

Gotchas / dead paths (do NOT repeat):
- Editing prompt.py / server.py with naive multiline string replacement broke
  indentation (3-space `except`). Always `ast.parse` after a patch; revert with
  `git checkout -- <file>` if broken.
- Do NOT persist a synthetic "compaction" message into the transcript: it
  breaks v214 (messages_after vs actual) and pollutes history. Use the SSE feed.
- tests derive REPO via 3x dirname (tests/acceptance/v*.py).
- `.gitignore` now excludes outputs/ mutants/ tests/.e2e/ caches; tests/ IS
  tracked. Only e2e/ is kept local.

Still open / next:
- CLI parity gaps remain: mcp add/remove/reload, providers CRUD, tools
  runtime/verifier/bestofn presets, jobs blocked_by/team create, context items
  (some added: sessions clear|model, context items, routines CRUD, jobs get).
- Optional: replace the prompt() rename with an inline editor.

## 2026-10-06 (cont.) — JAG-312 CLI parity + JAG-313 test-infra bug (commit 1b5f6c8+)

Shipped:
- Composer bar now has a VISIBLE `↺ reset` button (clear session chat+tasks),
  plus a `↺ reset session` entry in the ⋯ menu; Orbit agent row relabeled `↺ reset`.
- CLI parity closed: `mcp ls|add|remove|reload|local-file`, `providers
  ls|add|rm|default|rm-model`, `tools runtime|verifier|bestofn|difficulty|
  selfevolve|reasoning|approvals`, `routines ls|new|rm|enable|disable`,
  `jobs get` + `--blocked-by/--agents/--coordinator/--mode`, `context items`,
  `sessions clear|model`. Verified live against :8790.
- Docs for future agents: `AGENTS.md` (index), `.agent/README-debugging.md`
  (debug manual + bug-class checklist), `tests/README.md` (how to test).
- v311 (31 checks) + v312 (24 checks) lock all of the above.

Bug found & fixed (JAG-313):
- `pytest tests/properties/` NEVER ran — collection failed with
  `ModuleNotFoundError: sparkforge` (no src on sys.path). The nightly loop logged
  `props_exit=2` every iteration and it was never investigated. Fixed with
  `tests/conftest.py`. Property tests now pass (2/2).

Debug ladder state (JAG-313):
- ruff: 8394 findings (378 UP031 printf, 105 S110 try/except/pass, 69 BLE001,
  50 F821 — ALL in api_v02.py lazy-globals, intentional; 25 I001, 15 F401).
- mypy: 30 `var-annotated` (module-global hygiene, not errors).
- bandit: 19 B310 urlopen (router HTTP, controlled URLs), 4 B108 /tmp, 1 B103.
- battery: 73/73 GREEN (now 75 checks in v311+v312 detail).

Next:
- Optionally annotate the 30 mypy globals; migrate UP031 `%` → f-strings in bulk
  (risky: touches formatting, gate on the battery each batch).
- Wire `tests/properties/` into `battery.sh` optional section, or leave to pytest.

## 2026-10-06 (cont.) — JAG-314 cascade delete (deletion is a TRUE store delete)

Goal: audit every delete/clear path and answer "does deleting an object really
remove it from the store, or only hide it in the UI?" Fix the gaps.

Findings (audit via search sub-agent + source read):
- TWO severe dangling-reference defects:
  1. `DELETE /api/jobs/<id>` popped the job but left its id in every dependent's
     `blocked_by`; the dependent was wedged forever ("blocked by <gone>").
  2. `DELETE /api/sessions/<sid>` removed the files but never released the AGENT
     designation, so a later job/routine could resurrect the session via
     `get_or_create_session`; the ROLE.md and job/routine refs leaked too.

Fixes (uncommitted until battery green):
- jobs.py: `delete()` scrubs the id from all dependents (`_scrub_blocker`) and
  un-blocks them; `_blockers_state` tolerates a missing blocker (treated as
  satisfied — never a permanent deadlock); new `scrub_agent(aid)` drops an agent
  from every job's members/coordinator.
- agents.py: `release(session_id)` now cascades — scrubs the agent from jobs and
  deletes its routines. NOTE: keyed by SESSION id, scrubs by AGENT id.
- routines.py: new `delete_for_agent(agent)`.
- server.py `_purge_session_artifacts`: also purges the per-session ROLE.md;
  the session DELETE handler releases the agent after tombstoning.
- tests/acceptance/v314_cascade_delete.py (24 checks) locks all of the above.

SEGFAULT incident (root-caused, important for future tests):
- v314 initially printed `24/24 PASS` then the process died with SIGSEGV
  (exit 139) intermittently INSIDE battery.sh. Root cause: the test called
  `jobs.JOBS.wake()`, which dispatches a job and spawns a REAL daemon worker
  thread (`Thread(target=self._run, daemon=True)`). The main thread reached
  interpreter shutdown while the daemon thread was still executing → abrupt
  kill mid-C-call → segfault AFTER the PASS output.
- Fix: stub the runner first, exactly like v290 does:
  `jobs.JOBS._run = lambda jid: None`. v314 x10 → all exit 0; battery 74/74 GREEN.
- RULE for every acceptance test that touches jobs: ALWAYS stub `JOBS._run`
  before calling `wake()`/`dispatch()`, else a real worker thread spawns and can
  segfault the process at exit (looks like a flaky test, is actually a thread
  shutdown race).

Delete-semantics map (answered for the user):
- Session DELETE: TRUE delete (transcript+graph+runs+edits+backups+ROLE.md purged,
  tombstoned JAG-222, agent released JAG-314).
- Session CLEAR: NOT a delete — wipes messages + resets the task graph; session,
  agent and role survive (container stays).
- Job / Agent / Routine / Role / Provider / Provider-model / Skill / edits /
  taskgraph / term: TRUE store deletes.
- memory.py `invalidate()`: SOFT delete (filters retrieval, record stays on disk).
- checkpoints.py and approvals.py: NO delete at all (records accumulate).
- `_DELETED_SESSIONS` tombstone is IN-MEMORY only: after a server restart the
  anti-resurrection guard is empty. Candidate next bug (JAG-315).

Next:
- Commit + push JAG-314.
- Evaluate JAG-315: persist the deleted-session tombstones (or derive from a
  durable marker) so a restart cannot resurrect a deleted session.

## 2026-10-06 (cont.) — JAG-315 delete is FINAL (session resurrection fixed)

Goal: does deleting an object really remove it? Chase every way it can come back.

Bug (proved with scripts/check315.py, deterministic — no model):
- JAG-222 blocked a late *write* to a deleted session, but `get_or_create_session(sid)`
  DISCARDED the tombstone (`_DELETED_SESSIONS.discard(sid)`). Both `/api/chat` and
  `/api/chat/stream` call `get_or_create_session(body.get("session"))`, so a chat
  from a stale tab silently resurrects the deleted session as an empty transcript:
      after_delete tombstoned=True
      after_chat   -> id=SAME  tombstoned=False  file_exists=True   # BUG
- Also the tombstone set was in-memory only → lost on restart.

Fix (server.py):
- `get_or_create_session`: a tombstoned id is treated as gone; the caller gets a
  FRESH session (never the dead id), and the tombstone is KEPT (no discard).
- Tombstones are persisted to `SESSIONS_DIR/.deleted` (deliberately NOT `*.json`,
  so `list_sessions` never reads it) via `_persist_tombstones()` on delete, and
  reloaded by `_load_tombstones()` at import → survives a restart.

Tests: new `tests/acceptance/v315_session_delete_final.py` (13 checks).
`v222_delete_running.py` section B updated to the stricter contract (a deleted id
is not resurrected; the tombstone is retained) — the old B asserted the very
resurrection this bug was.

Verification: v315 13/13, v222 8/8, battery 75/75 GREEN (x2), import-all 43/0.

Debug-ladder state now: ruff 65 (E9/F401 etc.; many F401 intentional), mypy 30
var-annotated (cosmetic), bandit high = 0, battery 75/75, properties 2/2.

Next:
- Commit + push JAG-315.
- Continue fool-mode sweep: audit the 227 broad `except Exception:` sites for
  swallowed real errors; the delete semantics of memory (soft only) and
  checkpoints/approvals (no delete at all) remain by design — document if kept.

## 2026-10-06 (cont.) — JAG-316 session job labels are monotonic (no reuse)

Found live: two deleted smoke sessions both came back as `job: 12` → the id
counter had gone backwards.

Bug: `server._max_job()` took the max session `job` over LIVE session files only,
so deleting the session that held the top number let the next session reuse it.
Contract broken: "JX assigned once, never shifts" (JAG-169); and JX shares the
`J<n>` namespace with the orchestrator's own job ids (jobs.py `"J%d" % seq`), so
reuse is doubly wrong.

Fix (server.py):
- `_JOBSEQ_FILE = SESSIONS_DIR/.jobseq` (not `*.json` → never listed).
- `_max_job()` starts from a persisted high-water mark `_read_seq()` then maxes
  over live sessions; `ensure_job()` writes the assigned number via `_write_seq`.
  Monotonic across deletes, restarts and a fully wiped session store.

Test: new `tests/acceptance/v316_job_id_monotonic.py` (10 checks).
Verification: v316 10/10, battery 76/76 GREEN.

Next:
- Commit + push JAG-316.
- Seed/double-check `.jobseq` on the live system (reads existing sessions on
  first assign, so no manual seeding needed).

## 2026-10-06 (cont.) — JAG-317/318 finish delete-completeness for ALL objects

Goal: "does deleting really delete — for EVERY object?" Three object kinds still
lacked a true delete. Closed them, plus a broad swallow audit.

Broad `except Exception:` audit (scripts/audit_except.py, AST-based):
- 194 silent handlers (pass/continue/return None). Sampled the value-returning
  sites in tools/taskgraph/mcp_client/providers/routines/agents — all are
  documented best-effort guards (publish, open, loads, remove). No bug found;
  keep the script for future passes.

JAG-317 — memory had only a SOFT delete:
- `invalidate` is an append-only tombstone; `forget` (tool) was just an alias of
  it — nothing was ever removed. Added TRUE deletes:
  `memory.forget(mid)` rewrites the owning .md without the record and drops the
  tombstone; `memory.purge_invalidated()` bulk-compacts invalidated/expired.
  Exposed: tool actions forget/purge/erase/delete; POST /api/memory {action};
  DELETE /api/memory?target=; CLI `memory forget|purge`.

JAG-318 — checkpoints and approvals had NO delete at all:
- `checkpoints.delete(id)` drops the manifest + unlinks the payload;
  `checkpoints.prune(keep)` drops the oldest overflow.
- `approvals.delete(id)` removes the record AND its threading.Event (the old
  `_events` map leaked one Event per id, never pruned);
  `approvals.clear(status, keep_pending)` drops decided records, keeps pending.
  Exposed: DELETE /api/checkpoints/<id>, DELETE /api/checkpoints, DELETE
  /api/approvals/<id>, DELETE /api/approvals; CLI `checkpoints rm|prune`,
  `approvals rm|clear`.

Tests: v317 (18 checks), v318 (24 checks). v204 (soft-invalidate contract) stays
green. v198 prompt-bound stayed green after trimming the memory tool description.
Verification: v317 18/18, v318 24/24, v204 23/23, v198 prompt 16887<17000,
battery 78/78 GREEN, import-all 43/0. Live: store->forget removed 1, checkpoint
create->delete unlinked the file, approvals clear removed 500.

Delete-semantics map (now complete):
- TRUE delete: session, job, agent, routine, role, provider, model, skill,
  edits, taskgraph, term, MEMORY (forget/purge), CHECKPOINT (delete/prune),
  APPROVAL (delete/clear).
- SOFT (by design, audit trail): memory.invalidate tombstone.
- Session CLEAR still means wipe-contents (not delete).

Next:
- Commit + push JAG-317/318.
- Optional: surface forget/purge/checkpoint-delete/approval-clear in the WebUI
  (currently API + CLI only).

## 2026-10-06 (cont.) — JAG-319 WebUI wiring for the true deletes

- Memories panel (webui/index.html): per-record ✕ "forget (permanent delete)"
  on each search result (DELETE /api/memory?target=) + a 🧹 purge button
  (POST /api/memory {action:purge}). Both confirm first.
- Approvals panel: a "clear decided" button (DELETE /api/approvals; pending kept).
- Checkpoints have no WebUI panel (API + CLI only) — intentionally not wired.
- Test: v319 (10 checks) locks the client wiring; served HTML carries the
  handlers (2 hits each). battery 79/79 GREEN.

Next:
- Nothing outstanding on the delete-completeness thread. Optional future:
  a Checkpoints WebUI panel with delete/prune.

## 2026-10-06 (cont.) — JAG-320 a FAILED delegation can no longer be closed as done

Domanda utente: "una sessione coordinator ha chiamato un subagent, e' fallito, ma
il lavoro e' stato segnato done. Perche'? E' un bug?"

Risposta: SI', bug reale, con DUE difetti distinti (prova: sessione `d813720c6eac`,
grafo `d813720c6eac`):
1. Il testo dell'osservazione diceva "Subagent X finished (...)" ANCHE quando il
   subagent era andato in timeout → il modello credeva onestamente di avere il
   risultato (`{"ok": false, "error": "subagent timeout"}`).
2. `update_todos ... done` accettava QUALSIASI evidenza non vuota, senza incrociare
   l'esito reale della delega → lo step delegato veniva chiuso `done` (source
   `model:update_todos`) con evidenza inventata ("A5 produced the schema...").

Fix (JAG-320):
- `server._apply_chat_subagent`: registra l'esito e il testo di ritorno ora dice
  `FAILED: ... This delegated step is NOT done` (non piu' "finished").
- `taskgraph.record_delegation(graph, node_id, ok, ...)`: salva l'esito SUL NODO
  (campo `delegation`, durabile su disco). `ok=True` lo CANCELLA (retry riuscito).
  `taskgraph.clear_delegation(graph, node_id)`: consuma il marker.
- `server._apply_chat_todo_updates`: un `done` su uno step con marker di delega
  FALLITA viene RIFIUTATO (`refusing 'done'`) e il marker viene consumato
  (one-shot: un secondo tentativo genuino non e' bloccato per sempre).

Perche' sul nodo e non un timer in memoria: nel caso reale la chiusura `done` e'
arrivata ~8.6h DOPO il timeout (osservazione ts 1791146845.333, evidenza done ts
1791177792.201). Una finestra breve (900s) NON l'avrebbe intercettata; il marker
sul nodo sopravvive a gap lunghi e a restart, ed e' node-scoped (il fallimento di
uno step non blocca uno step diverso).

Test: `tests/acceptance/v320_failed_delegation_not_done.py` (13 check: blocco,
rifiuto one-shot, clear su successo, node-scoping, wiring). battery **80/80 GREEN**.
Static ladder: 0 errori nuovi (ruff 71 pre-esistenti altrove, mypy 30 baseline,
bandit-high 0).

Next:
- Nessun pending sul thread delega. Limite noto: l'evidenza di un `done` resta non
  verificata oltre "non vuota" — mitigato solo per le delegazioni; una verifica
  vera richiederebbe un verifier esterno (pattern heldout).

## 2026-10-06 (cont.) — JAG-321 "reset" non svuotava davvero la chat

Sintomo utente: i pulsanti reset (composer "↺ reset" in `webui/index.html` e
"↺ reset" per-agente in `src2/orbit_beta/web/orbit.html`) NON svuotavano del tutto
la chat. Dopo il reset riapparivano le card dei tool e le righe harness
(nudge / pivot / final / retry).

Causa: entrambe le UI chiamano lo stesso endpoint
`POST /api/sessions/<id>/clear`, che azzerava SOLO `sess["messages"]`. Ma il
transcript che la WebUI ricostruisce al reload (`loadHistory`) e' la fusione di
TRE store persistiti: `messages` + `tool_cards` + `injects`. Quindi card e inject
sopravvivevano e tornavano subito visibili.

Fix (JAG-321):
- Nuova `clear_session(sid)` in `server.py`: azzera `messages`, `tool_cards`,
  `injects`, resetta il task graph, purga i runtime map e pubblica
  `session.cleared`. L'endpoint ora delega a questa funzione (logica unica,
  testabile).
- Test: `tests/acceptance/v321_reset_clears_all.py` (10 check: i tre store
  svuotati, sessione mantenuta, task list reset, 404 su id ignoto, wiring).
  battery **81/81 GREEN**.

Verifica LIVE end-to-end (dopo restart del servizio): seed di una sessione con
messages+cards+injects → `POST /api/sessions/jag321live/clear` → file svuotato
(`msg=0 cards=0 injects=0`), cleanup del probe.

Nota: il reset LASCIA la sessione in elenco (0 msg) — e' il comportamento
documentato ("the session stays"); se l'utente vuole che sparisca serve la
delete ✕, non il reset.

Next:
- Punto "2)" della richiesta utente era VUOTO: nessun secondo sintomo indicato.

## 2026-10-06 (cont.) — JAG-322 job re-run + Paperclip-style delegation

Quattro richieste utente (la #4 "SEVERE").

**#1 — re-run di un job dopo aver cancellato l'agente.** Causa (prova:
`data/jobs.json`): J1/J2/J3 hanno `agents: []` + `coordinator: null` (una release
JAG-314 li ha "scrubbati"), e J3 e' stato rilanciato in 1 istante
(`started == ended`) → `_run` percorreva un roster vuoto, non faceva NULLA e
marcava comunque `done`. Il job J6 era invece BLOCCATO in `running` (`ended:
null`) → il pulsante "run" non faceva nulla (dispatch rispondeva "already
running"). Fix: `dispatch` RIFIUTA con motivo quando `agents` e' vuoto; `_run`
solleva ("no agents available …") quando gli agenti elencati non esistono piu' →
stato `error` visibile e ri-lanciabile; il reconcile allo startup chiude i
`running` interrotti; la UI Orbit ora mostra l'errore del dispatch (prima
silenzioso).

**#4 — delega stile Paperclip.** Prima: il worker riceveva il task come messaggio
"YOU" (nessuna attribuzione), il master non mostrava alcuna delega, nessun id di
sotto-job. Fix:
- `jobs.plan_subjobs(jid, agents, coord, plan, deps)` → SOTTO-JOB numerati
  `J6.1`, `J6.2` … uno per agente delegabile (il coordinatore NON e' un sotto-job),
  con `assignment/status/started/ended/result` salvati sul job (`subjobs`).
- `chat_stream_gen(..., sender=, subjob=)` scrive `sender`+`subjob` sul messaggio
  utente persistito; la WebUI (index.html `who()`) rende "A1 (Master) · J1.1"
  invece di "YOU".
- `jobs._delegation_msg` intesta il turno del worker con
  "Delegation from <coord> — subjob J…"; `_announce_delegation` scrive la stessa
  delega nella chat del COORDINATORE (inject `delegation`) → entrambe le chat
  mostrano il passaggio.
- Orbit: i sotto-job (id → agente · stato · durata) compaiono espandendo il job.
- `mode=fanout` gestito (il coordinatore non viene saltato, nessun header di
  delega).

**#3 — nome agente <-> titolo sessione.** `agents.AgentRegistry.sync_title`
(designate → scrive il titolo + pubblica `session.renamed`) e
`AgentRegistry.set_name` (endpoint `/rename` → aggiorna il nome). Verificato LIVE
nei due versi.

**#2 — icona Orbit piu' evidente.** In main app `#deck-open` ora e' un bottone
etichettato "🛰 Orbit" con bordo/testo accent (come "main app ↗" in Orbit).

Test: `tests/acceptance/v322_job_delegation_subjobs.py` (20 check; worker
attribuito, sotto-job numerati+timed, inject sul coordinatore, dispatch/run senza
agenti, sync nome↔titolo). Aggiornati i lock di firma in v296/v310 (sender/subjob)
e i lock stringa di v274/v275 (nuova `who(...)`). battery **82/82 GREEN**.
Verifica LIVE: `/` e `/orbit` 200, sync nome↔titolo nei due versi, J6 ri-lanciato
davvero (non piu' no-op). ruff/bandit ok (JS: esprima troppo vecchio per
index.html — errore pre-esistente identico su HEAD; orbit.html OK).

Next:
- La numerazione `J6.N` e' per-run (ricalcolata ad ogni dispatch). Se serve una
  storia persistente dei sotto-job tra ri-lanci, va versionata.

## 2026-10-06 (cont.) — JAG-323 phantom run (SEVERE): segnale "running" assente

Sintomo utente: una sessione-agente era IN ESECUZIONE (GPU occupata, token
consumati) ma il pannello sessioni a sinistra non mostrava alcun segnale; l'utente
se n'e' accorto solo dalla GPU e l'ha fermata a mano.

Causa (due buchi):
1. `list_sessions()` (payload di `/api/sessions`) NON esponeva un flag `running`.
2. `chat.run` era messo SOLO nella coda SSE del browser che avviava il turno, mai
   pubblicato sul feed GLOBALE (`chat.done` invece si'). Quindi ogni turno NON
   avviato da quel browser — un turno headless di job/routine su un'altra sessione
   — era invisibile: la riga restava "idle".

Fix:
- `server.list_sessions()` deriva `running` da `_ACTIVE_CHAT` (verita' lato server:
  OGNI turno, chiunque lo avvii, vi si registra per tutta la durata).
- `chat_stream_gen` ora `publish("chat.run", ...)` sul feed globale (simmetria con
  `chat.done`).
- `index.html`: il feed globale marca `setRunning(session, true)` su `chat.run` (per
  QUALSIASI sessione) e lo azzera su `chat.done`; `loadSessions()` semina il marker
  dal flag del server (cosi' un reload / un evento perso mostra comunque il run).

Test: `tests/acceptance/v323_running_signal.py` (8 check). battery **83/83 GREEN**.
Verifica LIVE: tutte le righe di `/api/sessions` hanno `running`; J6 finito con
sotto-job `J6.1` presente. Commit separati per tema (JAG-323 isolato da JAG-322).

Next:
- Il feed `backlog` non rigioca `chat.run`; un browser aperto a meta' turno si
  affida al flag del server in `loadSessions` (gia' coperto).

## 2026-10-06 (cont.) — JAG-324 gerarchia dei SUBJOB (modello oggetti a 4 livelli)

Finding FONDAMENTALE dell'utente: un agente (= sessione) puo' avere PIU' subjob, e i
subjob hanno dipendenze fra loro, come i todo ma un livello piu' in alto; i todo
stanno sotto l'agente MA ANCHE sotto il subjob `Ji.j` che li ha prodotti. Il modello
degli oggetti e' quindi a QUATTRO livelli, contenuti l'uno nell'altro, e i legami
devono restare coerenti in TUTTO il codice:

    Job JN -> Subjob JN.j -> Agent AX (= sessione) -> Todo AX.TY

Prima esistevano solo tre livelli (Job/Agent/Todo): il subjob `J6.1` era disegnato
nella chat (JAG-322) ma NON esisteva nei dati -> non era ne' nominabile in modo
stabile, ne' ordinabile (deps), ne' mappabile nella costellazione.

Fix (i due invarianti che tengono insieme i livelli):
- I TODO portano ENTRAMBI i tag: `jid` (job) E `subjob` (JN.j). `taskgraph.add_node`
  copia `graph["jid"]`/`graph["subjob"]` nel nodo; `chat_stream_gen` scrive
  `_existing["subjob"] = subjob` per il turno (e `None` sul turno manuale). Un
  subjob "abbraccia" cosi' il sottoinsieme dei todo del SUO agente con quel tag.
- I SUBJOB formano un DAG: `jobs.plan_subjobs` in 2 passate assegna `JN.j` per agente
  (ordine a onde) e poi `deps` = i subjob degli agenti da cui dipende (rispecchia il
  DAG agent-level). Stessa idea delle deps dei todo, un livello sopra.

Viste allineate (nessuna inventa il livello):
- `jobs.subjob_todos(jid)` = pivot read-only del todo-store -> {subjob -> [todo id]};
  `jobs.detail(jid)` arricchisce il job con `subjobs[*].todos`.
- `orchestration`: `GET /api/jobs/<id>` usa `detail`.
- `orbit_beta/api._subjobs_of` + `_constellation` espongono il livello `subjobs`.
- Orbit: corsia subjob (una pill `JN.j -> AX` per subjob) con edge job->subjob,
  subjob->subjob (deps) e subjob->agente.
- App principale (`index.html`): chip subjob accanto al chip job nel task tree.

Test: `tests/acceptance/v324_subjob_hierarchy.py` (15 check). battery **84/84 GREEN**.
Static pulito (ruff ok, bandit niente high, orbit.html JS ok). Commit dedicato a
JAG-324 (docs incluse): `design-agents-jobs.md` aggiornato al modello a 4 livelli.

Next:
- I subjob sono definiti al DISPATCH; un subjob senza todo (agente che non ne crea)
  resta con `todos: []` -> corretto, ma la UI deve poterlo mostrare come "vuoto".

## 2026-10-06 (cont.) — JAG-325 phantom run, TUTTI gli entry point (SEVERE)

Seguito di JAG-323. Quella fix aveva insegnato il segnale "running" SOLO al path
STREAMING (`chat_stream_gen`). Ma due altri path eseguono un turno REALE del modello
senza registrarsi in `_ACTIVE_CHAT`:
1. l'handler SINCRONO `POST /api/chat` (server.py);
2. `api_v02.LocalApi.chat` — il bridge MCP in-process (`POST /mcp`).
Per entrambi la sessione risultava IDLE nel pannello mentre la GPU/token bruciavano:
lo STESSO phantom run (SEVERE).

Fix: un bracket CONDIVISO, non piu' logica duplicata per handler.
- `server.turn_begin(sid)` -> registra in `_ACTIVE_CHAT` (+`chat.run` sul feed
  globale) e ritorna un TOKEN per-turno.
- `server.turn_end(sid, tok)` -> rilascia SOLO la propria registrazione (un turno
  vecchio che finisce tardi NON spegne uno piu' nuovo) + `chat.done` sul feed.
- Path sincrono `/api/chat`: `_turn_tok = turn_begin(...)` prima della chiamata e
  `turn_end(...)` in un `finally` (esce anche sul 502).
- `api_v02.LocalApi.chat`: stessa coppia con `try/finally`.

Regola: il segnale "running" NON e' proprieta' di un handler — ogni entry point deve
avvolgere la chiamata al modello nel bracket condiviso.

Test: `tests/acceptance/v325_phantom_run_all_paths.py` (14 check). battery
**85/85 GREEN**. Static gate (E9,F63,F7,F82,F401) pulito sui file toccati.

Next:
- `agent_run_v2` / i run autonomi (`/api/agent`, subagent) NON passano per
  `_ACTIVE_CHAT`: hanno un proprio RunState. Se devono compariere nel pannello
  sessioni, vanno agganciati al bracket condiviso in una prossima iterazione.

## 2026-10-06 (cont.) — JAG-326 ordine NATURALE dei subjob (id ordinali)

Bug: i subjob sono `JN.1 … JN.10`. Un sort di STRINGHE mette `JN.10` PRIMA di `JN.2`,
quindi un job con 10+ subjob li elencava fuori ordine in DUE punti:
- `jobs._announce_delegation` (il record di delega nel chat del coordinatore);
- Orbit `JobsView` (`Object.keys(subs).sort()`).

Fix: chiave numerica condivisa.
- Python: `jobs.subjob_num(sub_id)` (ultimo indice; fallback 0) usata come `key`
  nel sort dell'announcer.
- Orbit: helper `_jn(s)` = ultimo gruppo di cifre dell'id, usato nel comparator del
  JobsView.

Test: `tests/acceptance/v326_subjob_natural_order.py` (9 check; include la prova che
il sort-stringa SBAGLIA). battery **86/86 GREEN**. orbit.html parse OK (esprima);
l'errore in index.html riga 171 e' PRE-ESISTENTE (non introdotto qui).

Next:
- (resta) i run autonomi non passano per `_ACTIVE_CHAT` (vedi JAG-325).

## 2026-10-06 (cont.) — JAG-327 un subjob abbraccia solo i todo del SUO RUN

Era il "resta" di JAG-326. Su RE-RUN di un job gli id subjob si RIPETONO (`J6.1`
ricompare) ma il lavoro e' di un RUN nuovo. `_scope_graph` apre un nuovo plan solo
quando cambia il JOB id, invariato sul re-run -> il subjob finiva su DUE plan e
`subjob_todos` univa i todo del run precedente (coerenza rotta).

Fix (due meta'):
1. `jobs._run` apre un PLAN fresco per ogni agente che partecipa al run quando e' un
   RE-RUN (`g["jid"] == jid`); il PRIMO run lo apre gia' `_scope_graph` (jid None->JN).
2. Le viste read-only `JobRegistry.subjob_todos` e `orbit_beta.api._subjobs_of`
   limitano un subjob al PIU' RECENTE plan in cui e' comparso
   (`jobs.latest_plan_nodes`): cosi' un plan successivo e NON correlato sulla stessa
   sessione NON cancella la mappa (il "solo plan corrente" l'avrebbe fatto).

Test: `tests/acceptance/v327_subjob_run_scope.py` (12 check). battery **87/87 GREEN**.
Static gate (E9,F63,F7,F82,F401) "All checks passed!".

## 2026-10-06 (cont.) — JAG-328/329 costellazione + tabella agenti (UI)

JAG-328 (frecce): la costellazione disegnava la freccia job->agente verso OGNI membro
(`J7 -> A8` E `J7 -> A9`), ma il job e' assegnato al SOLO coordinatore; il pezzo dato
ad A9 e' il SUBJOB `J7.1`. Edge FALSO che duplicava la freccia del subjob. Fix in
`orbit.html`: l'edge job->agente parte SOLO dal coordinatore (`j.coordinator`); i
membri si raggiungono via `subjob -> agente`. Un job fan-out (senza coordinatore) non
disegna frecce job->agente.

JAG-329 (dropdown modello che sparisce): la tabella agenti di Orbit si ricostruisce
ogni 5s (`setInterval(refresh, 5000)`). Il guard rimandava il rebuild solo se un
INPUT/TEXTAREA era attivo, NON se un `<select>` (MODEL / REPORTS-TO) era APERTO: il
poll chiudeva il menu mentre lo si sceglieva. Fix: il guard copre anche `SELECT`.

Test: `v328_job_edge_to_coordinator.py` (5), `v329_select_survives_poll.py` (5).
battery **89/89** al commit di questo blocco.

## 2026-10-06 (cont.) — JAG-330 SEVERE: il master DICHIARA le dipendenze dei subjob

Sintomo utente: in un job coordinato, coder 2 doveva lavorare DOPO coder 1, ma i due
subjob partivano IN PARALLELO — nessuna dipendenza impostata. Le deps venivano solo
dalla config del job (`deps`), mai dal MASTER, che quindi non strutturava l'ordine.

Fix (Paperclip-style: il coordinatore dichiara il DAG, il runner lo impone):
- Prompt del coordinatore: chiede di terminare un bullet con `(after AX)` quando quel
  teammate deve ASPETTARE; niente dipendenza se l'ordine non conta.
- `jobs.parse_plan_deps(plan)` -> `{agent: [deps]}` dalle dichiarazioni `(after AX)`.
- `jobs.merge_deps(job_deps, declared)` = deps dell'utente UNION declarate.
- `_run`: calcola `deps` effettive, le usa SIA per `plan_subjobs` (ogni subjob porta i
  suoi `deps`) SIA per `waves(...)` -> chi dipende parte solo dopo che i thread delle
  onde precedenti sono stati JOINati = deterministico.
- Le deps sono salvate sul job (`declared_deps`) e MOSTRATE nel chat del master
  (`J8.2 -> A11 (...): ... [after J8.1]`) e nel messaggio al worker ("Waits for ...").

Test: `tests/acceptance/v330_declared_subjob_deps.py` (14 check; catena A8->A9->A11 su
tre onde, subjob J8.2 dipende da J8.1). battery **90/90 GREEN**. Static gate pulito.

## 2026-10-06 (cont.) — JAG-331/332 harness: il worker ESEGUE + marker di avvio

CONTESTO (verifica con dati REALI, script `trash/diag_prompt.py`): l'utente temeva che
ROLE.md avesse "sostituito tutto" e che RULES.md non fosse passato. GROUND TRUTH sul
server live:
- system prompt COMPLETO = 18894 char -> identity 255, prompt-map 687, rules-policy 427,
  skills-policy 586, memory-policy 1017, capability 385, task-policy 1816,
  self-summary 733, agent-role 121, tools 7232, rules 2939, skills 2674, memory 0.
- RULES.md E' passato (blocco rules 2939). ROLE.md e' un PATCH di 121 char
  (agent-role), NON una sostituzione. Tool/skill discovery presenti.
=> il prompt era corretto: la causa del guasto era ALTRA.

JAG-331 (SEVERE, la vera causa): il messaggio di delega al worker finiva con
"Deliver ONLY your part as concise plain text now" + "keep the reply short". Il worker
(coder 2) ha quindi RISPOSTO con un piano e "no callable tools" invece di eseguire.
Fix: `_delegation_msg` ora ordina di FARE il lavoro end-to-end con i tool e le skill
(skills{action:'search'|'list'}) e riportare il RISULTATO; non "descrivere".

JAG-332: il marker di sistema col prompt completo e' TRANSIENTE (kind 'system', non
persistito) -> dopo un reload NON si vede alcun messaggio harness all'avvio. Fix:
`server._harness_start_note(sess)` scrive UNA volta per sessione (primo turno) un
inject durevole `harness-start` (workspace / rules / skills / tools / dimensione
prompt) e lo pubblica sul feed.

Test: `v331_worker_executes.py` (9), `v332_harness_start_marker.py` (9).
battery **92/92 GREEN**. Static gate pulito.

## 2026-10-06 (cont.) — pulizia repo + JAG-333..336 (plan master, id annidati, UI job, org complesso)

PULIZIA (commit chore 41eebb6): 867 file GENERATI erano tracciati pur essendo in
`.gitignore` (outputs 652, mutants 188, tests/.e2e 13, trash 13, eval/results 1) ->
`git rm --cached` (i file restano su disco). Tracciati: ~1233 -> 366.

JAG-333 (item 1): il MASTER non aveva un piano. NON e' un bug "casuale": i turn di job
non sono mai auto-pianificati (JAG-308) e il coordinatore e' istruito a non usare tool
-> nessuno creava la sua task list. Fix: `_seed_coordinator_plan` scrive UN todo per
subjob (tag subjob id) sul grafo del coordinatore.

JAG-334 (item 4): id annidati. `subjob_id(jid, n, parent_sub)` + `plan_subjobs(parent_sub=)`
-> `J8.1`, e un lavoro dato DENTRO un subjob diventa `J8.1.1`, `J8.1.2`… (profondita' =
livello organigramma dell'agente che riceve).

JAG-335 (item 5): pannello job Orbit. Le righe subjob sono ORA indentate per profondita'
e CLICCABILI -> aprono la chat dell'agente; la lista piatta `runs` (A8 done, A9 done,
A11 running) e' stata RIMOSSA: contano solo gli indici `JN.j`.

JAG-336 (item 6): test "organigramma complesso". Una S.p.A. sintetica (12 agenti,
CEO -> C-suite -> lead -> dev) con catena di dipendenze multi-livello; verifica onde
deterministiche, deps dei subjob, annidamento. In batteria. (Non c'e' un clone locale
di Agency-Agents: profili sintetizzati nello spirito di quel repo.)

JAG-332 (item 2): wording del marker reso ACCURATO — il system prompt va rispedito ad
OGNI richiesta (API stateless); il provider riusa la KV-cache, quindi e' ricalcolato
solo dopo compaction/reset.

Test: v333 (6), v334 (9), v335 (6), v336 (14). battery **96/96 GREEN**. Static pulito.

---

## 2026-10-06 (cont.) — JAG-337: esito del worker esplicito + retry + escalation nei DUE chat

PROBLEMA (SEVERE, segnalato dall'utente): nell'ultimo run "coder 2" ha FALLITO, non e'
stato ritentato, e la palla e' tornata al master SENZA alcuna traccia in nessuno dei due
chat. Regola Paperclip: non restare MAI in silenzio su lavoro bloccato.

FIX (jobs.py):
- `_STATUS_RE` + `parse_status(reply)`: il worker chiude il report con una riga esplicita
  `STATUS: DONE` / `STATUS: BLOCKED: <perche'>` / `STATUS: FAILED: <perche'>`.
  `_delegation_msg` ora lo richiede. Se manca lo STATUS, l'esito e' DONE SOLO se non
  restano step APERTI (`open_steps`), altrimenti BLOCKED.
- `_one` RISCRITTO: fino a `SPARKFORGE_JOB_RETRIES` (default 1) tentativi extra; ogni
  tentativo non-DONE genera un reinject "Resume subjob ..." al worker.
- `_log_escalation`: scrive un inject `handoff` nel chat del WORKER ("returning subjob
  ...") E in quello del COORDINATOR ("... could not finish subjob ... — BACK TO YOU").
- Subjob che fallisce = `failed` (MAI `done`); il messaggio di sintesi al master elenca
  gli "UNFINISHED SUBJOBS"; il job porta `failed_subjobs` e status `partial`.

Q1 (Stop su modelli cloud): gia' confermato provider-agnostico in `_router_stream` —
`cancel()` e' controllato nel read-loop sia per il router locale (llama.cpp) sia per
OpenRouter, quindi lo Stop chiude anche le chiamate cloud (JAG-197).

Test: v337 (23). battery **97/97 GREEN**. Static pulito.

---

## 2026-10-06 (cont.) — JAG-338 (master autonomo) + JAG-339 (livello TEAM)

JAG-338 (item 1): il master PUO' usare tools/skills e scrivere il PROPRIO piano. Prima il
turno di decomposizione diceva "do NOT call any tool" -> il coordinatore non poteva ne'
usare skill ne' pianificare, e l'harness doveva seminare il piano (JAG-333). Ora:
"You MAY use your tools and skills ... you SHOULD record your plan in your own task
list"; resta vietato lo spawn di subagent. `_seed_coordinator_plan` e' divenuto un
FALLBACK: se il master ha gia' scritto dei todo nel piano corrente, NON duplica.

JAG-339 (item 4+5): nuovo livello TEAM. Oggetto reale `TN` (T1,T2,...) in
`src/sparkforge/teams.py` (`TeamRegistry`, store `data/teams.json`). Un agente puo'
stare in PIU' team (`agent.teams`); la membership e' POSSEDUTA dal team
(`team.members`) e `agents.py` la legge soltanto (`teams_for`) -> niente drift.
API: `GET/POST /api/teams`, `GET/POST/DELETE /api/teams/<id>`,
`POST /api/teams/<id>/members`; `/api/agents` e `/api/agents/tree` espongono `teams`.

UI: Orbit ha un SELETTORE di team nell'header che scopa Agents, Org chart, Job e
Constellation (`/api/orbit/constellation?team=TN`); `ALL` = tutto. La main app mostra
il simbolo del team su ogni riga di sessione. (Decisioni lockate con l'utente: id `T1`;
multi-team; non display-only.)

Naming: il todo della chat passa da `AX.TY` a `AX.nY` (`T` ora e' il namespace TEAM; i
node id erano gia' `n1,n2`). Aggiornati index.html `_todoid`, orbit.html `label`, e i
commenti/docstring.

Seed (item 5): `scripts/seed_teams.py` legge il clone locale di agency-agents
(`strategy/runbooks.json` + frontmatter degli agenti) e crea 3 team con organigramma
reale (coordinator -> lead di gruppo -> specialisti). Idempotente
(`SPARKFORGE_AGENCY_DIR`). Eseguito: T1 Startup MVP Build, T2 Multi-Channel Marketing
Campaign, T3 Incident Response — 30 agenti creati.

Test: v338 (9), v339 (22), v340 (11), v341 (10). battery **101/101 GREEN**. Static pulito.
Spec: `docs/specs/2026-10-06-teams-level-design.md`.

---

## 2026-10-06 (cont.) — JAG-342: layout Orbit a colonna singola + ORG CHART intero

Segnalato: l'ORG CHART era tagliato (non mostrava tutto l'organigramma), la pagina
prendeva una scrollbar orizzontale mentre il chart aveva ANCHE il pan a transform
("se c'è il pan a che serve la scrollbar?"), e i pannelli erano disposti male.

Fix (orbit.html): ogni riga della pagina e' ora UNA COLONNA (mobile-style, full width);
l'ORG CHART scorre NATIVAMENTE nel suo pannello (transform pan RIMOSSO); cambiando team
il focus della constellation si resetta (prima restava "A8 MASTER" fuori dal team).

Flussi agenti (verifica, punto 1 utente): GIA' visibili. Ogni inject (delegation,
handoff, ...) viene renderizzato in chat come blocco "🔌 harness → LLM [kind]"
(`harnessInject`, index.html) e ricostruito al reload (`loadHistory`). Quindi i
messaggi scambiati tra agenti — incluso il fallimento che torna al master — si vedono.

Test: v342 (8); v311 aggiornato (pan rimosso). battery **102/102 GREEN**. Static pulito.

---

## 2026-10-06 (cont.) — JAG-343: policy modelli di team

Regola utente: un team NON puo' avere piu' di UN modello LOCALE per macchina (dgx e win);
agli altri modelli cloud ECONOMICI; i cloud piu' forti (ma sempre eco) ai CAPI.

Implementato (`teams.py` + `agents.set_model` + `orchestration` + Orbit):
- `machine_of(ref)`: classifica un ref come macchina locale (dgx/win, provider con
  `local:true`) o cloud; `None` = default locale (dgx).
- `assign_models(team)`: i CAPI (chi ha riporti nel team, o le radici) -> LEAD_MODEL
  forte-economico; il resto -> MEMBER_MODEL economico; resta al massimo UN locale per
  macchina tra i NON-capi (un capo non tiene mai un locale).
- Guardia su OGNI set: `local_conflict` rifiuta un 2o locale sulla stessa macchina nel
  team (`POST /api/agents`).
- API `POST /api/teams/<id>/models`; bottone "model policy" in Orbit; `seed_teams.py
  --models`. Override: `SPARKFORGE_TEAM_LEAD_MODEL` / `_MEMBER_MODEL` / `_LOCAL_SLOTS`.

Default scelti con l'utente: lead `openrouter:z-ai/glm-5.3-flash`, membri
`openrouter:deepseek/deepseek-v4-flash-0731`; cap 1 locale/macchina. Applicato ai 3 team
live. Nota: con agenti condivisi tra piu' team l'assegnazione finale e' l'ultima
eseguita (resta comunque <=1 locale per team, il cap puo' solo scendere).

Test: v343 (18). battery **103/103 GREEN**. Static pulito.

---

## 2026-10-07 — JAG-344: il turno di PIANIFICAZIONE del coordinatore e' "plan-only"

Bug trovato DAL VIVO (WebUI/Orbit): il master COMPLETAVA TUTTO IL LAVORO DA SOLO nel suo
turno di pianificazione — scriveva i file del deliverable (`kickoff/01..04.md`) e si
auto-verificava — BYPASSANDO il team, invece di limitarsi a scomporre il goal.

Causa: il turno di pianificazione girava con il budget tool pieno (8 step) E il loop di
continuazione (`keepgoing`) che lo spronava a "chiudere ogni step con evidenza". I suoi
todo (la delega) non sono lavoro suo, ma il loop lo trattava come tale.

Fix:
- `server.chat_once(..., plan_only=False)` + `chat_stream_gen(..., plan_only=...)`: un
  turno plan-only ha un budget tool RISTRETTO (`PLAN_ONLY_MAX_STEPS`, default 3) e NON
  entra MAI nel loop di continuazione — esce con stop tipizzato `plan_only`.
- `jobs._run_agent(..., plan_only=...)`: il turno coordINatore di pianificazione passa
  `plan_only=True`; il prompt gli dice esplicitamente "This turn is for PLANNING ONLY".

Verifica LIVE (J12): il cap da solo NON basta — il master scriveva comunque 2 file del
deliverable prima di fermarsi. Aggiunto il guard READ-ONLY: in un turno plan-only solo
`PLAN_ONLY_TOOLS` (`fs.read`, `skills`, `memory`, `self`) puo' girare; `shell` /
`fs.write` / `fs.edit` / `subagent` vengono RIFIUTATI con `_plan_only_refusal` (il
modello viene rimandato a PIANIFICARE). Cosi' il master informa il piano e stop.

Secondo bug (stesso run): TUTTI i subjob ricevevano lo STESSO assignment. Il piano
conteneva una riga aggregata ("critical path: A13 -> A14 -> A15") e `_assignment_for`
restituiva la PRIMA riga contenente l'id — che combaciava per OGNI agente. Ora sceglie la
riga PIU' SPECIFICA: prima id = l'agente stesso, minimo numero di ALTRI agenti.

Terzo: in Orbit l'etichetta SVG della costellazione stampava ancora `A12.T1` (la vecchia
convenzione). Corretto `_nodesSvg` + hint a `.n`; rafforzato v340 C3 e allineato v293
(che asseriva la vecchia `.TY`).

Test: v344 (14) nuovo; v293/v310/v322/v340 aggiornati. battery **104/104 GREEN**. Static pulito.
Prossimo: ri-eseguire il job complesso dal vivo e verificare la checklist (todo chiusi,
deliverable, scambio messaggi, skill discovery, errore != retry/close).

---

## 2026-10-07 (cont.) — verifica E2E live della catena di team (WebUI/Orbit)

Harness :8790 su DGX; token da `z:\.config\sparkforge\env`; browser via Chrome DevTools MCP.
Workspace degli agenti = `/home/jagones/Repositories/TESTS/Jago` (fuori dal repo).

**J12** (team T1 "Support": coordinatore A24 + A25..A29) — catena ORDINATA creata DALLA UI
(`#jobGoal` + `#jobTo`=A24 + `#jobCreate` + bottone run):
- gerarchia forzata e rispettata: `J12.1(A25)→J12.2(A26)→J12.3(A27)→J12.4(A28)→J12.5(A29)`.
- artifact `support/`: `retention.csv`, `summary.md` (header+trend di A26, poi `## Method`
  A27, poi `## Benchmark` A28 — nell'ordine ESATTO: prova che l'ordine e' stato imposto),
  `README.md`. Job `done`, 0 subjob falliti.
- **tutti i todo chiusi**: `open=0` per A24..A29 (letto da `data/graphs/<session>.json`).
- deliverable = sintesi di A24 (4251 char) con catena e numeri.
- scambio messaggi: inject `delegation` nel chat del coordinatore + messaggio "Delegation
  from A24 ... subjob J12.4" nel chat del worker (entrambi i lati). OK.

**J13** (stesso team, goal `viz/`, step grafico A28) — verifica del FIX plan-only:
- il turno di PIANIFICAZIONE ha usato SOLO `write_todos`/`update_todos`: **zero
  fs.write/shell** → il master NON esegue piu' il lavoro. FIX CONFERMATO LIVE.
- assignment **per-agente** corretti (`J13.1 "A25: ..."`, `J13.2 "A26: ..."`, ...): fix OK.
- artifact `viz/`: `metrics.csv` (14 righe), `insights.md`, `README.md`, `trend.png`
  (PNG reale 1500x825). Job `done`, tutti i todo chiusi.
- **SKILL DISCOVERY: NON esercitata** — nessun agente ha chiamato il tool `skills` (0 call).
  Il meccanismo esiste ed e' funzionante: `/api/skills` = 179 skill; la harness-start note
  consegna "skills index: 2674 char"; il messaggio di delega pubblicizza `skills{...}`.
  Gli agenti hanno risolto con shell/python. FINDING (non bug): la scoperta e' POSSIBILE e
  automatica, ma non viene attivata se il task e' risolvibile senza.
  PROVA POSITIVA del tool: `POST /api/tools/call {tool:'skills', args:{action:'list'}}`
  → executed, count=179; `{action:'read', name:'chart-visualization'}` → executed e legge
  il SKILL.md (in cinese; genera il chart via API AntV con curl — probabile motivo per cui
  l'agente, con la rete sandboxata, ha preferito matplotlib locale).

**J14** (coordinatore A19 + worker A20) — percorso di ERRORE:
- goal che obbliga A20 a leggere un file inesistente e chiudere con `STATUS: BLOCKED: ...`.
- osservato: `J14.1` → `retrying` (retry BOUNDED, JAG-337) → `failed` (attempt 1, error
  "file zzz-must-not-exist.txt is missing."); run `A20` = `failed`; job = **`partial`** con
  `failed_subjobs=["J14.1"]`.
- il coordinatore NON dichiara successo: la deliverable finale riporta onestamente che il
  file NON esiste. Quindi l'errore NON viene chiuso come "fatto".

**FINDING infrastrutturale** (non corretto, rischio): un provider cloud silenzioso
(deepseek-v4-flash in coda) puo' tenere un turno ~11 min con 0 token
(`ROUTER_IDLE_TIMEOUT=120s` → fallback non-stream `timeout=300s`). Bounded ma molto lento.
Da valutare un cap TOTALE per turno.

Test: battery **104/104 GREEN** (nessuna modifica di codice in questo giro di verifica).

---

## 2026-10-07 — Release v1.0.0: pulizia repo + README marketing + struttura docs

Richiesta utente: pulire il repo (struttura, `.gitignore`, cose obsolete), README in stile
marketing per attirare download, progetto GitHub professionale. Posizionamento: NON una
meta-harness tipo Paperclip; una harness unica che GUIDA bene l'LLM, e sopra **meta-agenti
in TEAM** (ogni agente = una harness completa: tool, skill, piano, memoria, chat).

Fatto:
- `.gitignore` irrobustito (`+ .hypothesis/`, `*.pyc/*.pyo`, junk OS/editor); dal disco
  rimossi `README.md.bak-fix` e le cache (`__pycache__`, `.pytest_cache`, `.ruff_cache`,
  `.mypy_cache`, `.hypothesis`).
- `README.md` RISCRITTO (marketing, v1.0.0): "the agent harness built to DRIVE the LLM",
  modello a 5 livelli, feature highlights, install, quality gate, docs, license.
  + `assets/banner.svg`, `assets/logo.svg`.
- Nuovi: `CHANGELOG.md` (Keep a Changelog), `CONTRIBUTING.md`, `.github/` (workflow CI che
  esegue la battery + issue/PR template), `docs/README.md` (indice).
- `docs/` riordinato: `specs/ plans/ research/ evidence/` + `PLAN.md` + `WAYFORWARD_minor.md`
  → `docs/archive/`; `docs/` tiene solo `ARCHITECTURE.md`, `CLI.md`, `README.md`,
  `RESEARCH-frontier-harnesses-2026.md`, `TESTING-PLAYBOOK.md`, `diagrams/`.
  `ARCHITECTURE.md` RISCRITTO per la v1.0.0.
- `AGENTS.md`: 73/73 → 104/104, + modello a 5 livelli. `VERSION` 0.7.1 → 1.0.0
  (`server.py`; `console.html` demo).
- battery **104/104 GREEN**. Rilascio PUBBLICATO: 5 commit atomici (hygiene → README+assets →
  CHANGELOG/CONTRIBUTING/.github → docs archive+ARCHITECTURE → VERSION 1.0.0), `master`
  pushato (`11d740d..190ff4b`), tag annotato **v1.0.0** pushato, GitHub Release creata:
  https://github.com/jagones84/sparkforge/releases/tag/v1.0.0. Working tree pulito.
