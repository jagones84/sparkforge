# SparkForge — HANDOFF (sessione autonoma notturna)

Ultimo aggiornamento: 2026-10-04 (notte, agente autonomo).
Branch: `master`. Ultimo commit: `02d6d33` (JAG-197).

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

### Memoria generica (Hindsight MCP)
- Le lezioni *generiche* di ingegneria imparate qui sono state salvate via MCP
  Hindsight (`retain`, bank `cccc-shared`): scritture atomiche con temp unico,
  cancellazione cooperativa, read-modify-write nel lock, fallback che rispetta
  cancel, handler HTTP graceful, progressive disclosure delle capability.

### Test LIVE (richiedono il server up) — cartella `tests/live/`
- `v199_endpoint_sweep.py` (51/51), `v200_concurrent_chat.py` (7/7),
  `v202_concurrent_stream.py` (4/4). NON nel gate `battery.sh`.

Battery: v140 9/9, v177 OK, v183 28/28, v195 21/21, v198 26/26, v204 20/20
→ **6/6 GREEN**.

### Test: convenzione nomi (richiesta utente punto 0/4)
- Cartella `tests/`, file `v<NNN>_<slug>.py` (numero = ticket JAG, slug descrittivo).
- Gate ufficiale = `tests/battery.sh` (oggi: v140, v177, v183, v195, v198, v204).
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

Fatto in questa sessione (tutti i punti 0-5 avviati):
1. Ricerca web harness/skills/MCP/failure-modes → doc in `docs/research/`.
2. `tests/v198_skills_tools_awareness.py` (19/19) + `skills{action:"search"}`.
3. Test live `tests/live/` (v199 endpoint sweep 51/51, v200 7/7, v202 4/4).
4. Bug trovato e risolto: **JAG-201** (concorrenza stessa sessione).
5. **RDD in corso** — P5 (audit skill, JAG-203), P2 (verifica memoria, JAG-204,
   con bug parser reale corretto). Prossimi P1 (step auditor) e P3 (budget).

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
- `docs/plans/`, `docs/specs/` — piani e design.
- `tests/legacy/v095_prm.py`, `v145_bestofn.py` — PRM / best-of-N (parte unica).
