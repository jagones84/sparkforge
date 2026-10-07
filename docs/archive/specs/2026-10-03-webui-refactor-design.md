# WebUI refactor — design (JAG-150)

Data: 2026-10-03 · Stato: **proposto, in attesa di review**
Autore: agente (decisioni delegate dall'utente) · Backup pre-refactor: tag `backup-pre-webui-refactor-20261003-115345`

## 1. Obiettivo

Rendere la WebUI di SparkForge più vicina a Trae: **meno bottoni**, gerarchia chiara,
operativo a destra, config in una **finestra Impostazioni mobile**.
**Vincolo assoluto: nessuna funzione di gestione oggi presente nella WebUI deve sparire.**

## 2. Layout target

```
┌───────────────────────────────────────────────────────────────────────┐
│ TOPBAR: ⚡ SPARKFORGE · ctx · compact · model ▾ · sandbox · server ·    │
│         feed · ▤ sessioni · ▥ inspector · ⚙ impostazioni · ⌘K          │
├──────────┬────────────────────────────┬─────────────┬─────────────────┤
│ SESSIONS │  CHAT  +  EDITOR (centro)   │  INSPECTOR   │  (finestra ⚙    │
│ (sx)     │  (l'editor tra chat e dx)   │  (sezioni)   │   mobile sopra) │
└──────────┴────────────────────────────┴─────────────┴─────────────────┘
```

- **SX · Sessions**: invariata (nome + `msg · tempo` sotto; search, hide-empty, new, delete).
- **Centro · Chat + Editor**: invariati (log, CoT drawer, composer send/queue/steer/agent/stop/editor,
  slash menu, textarea; editor CodeMirror a tab).
- **DX · Inspector**: una **colonna scrollabile a sezioni richiudibili**, niente tab, niente bottoni.

## 3. Inspector — sezioni (solo dati esistenti)

| # | Sezione | Contenuto (riuso markup/JS attuale) |
|---|---------|-------------------------------------|
| 1 | **Plan / Tasks** | goal + reset, run graph (add node, replan, reset), task detail, remaining (ex pannello *graph*) |
| 2 | **Context** | meter grande + msgs/tok/budget + bottone **compact now** (ex sezione *Context*) |
| 3 | **Approvals** | approvazioni pendenti (ex pannello *approvals*) |
| 4 | **Files & changes** | albero file + lista modifiche + undo/diff + "apri editor" (ex pannello *files*) |
| 5 | **Feed** | eventi live (ex card *feed*) |

Stato aperto/chiuso di ogni sezione persistito in `localStorage` (`sf_insp_<sezione>`).

## 4. Impostazioni — finestra mobile (⚙)

Finestra **trascinabile / ridimensionabile / minimizzabile / chiudibile (✕ · Esc)**,
**non bloccante** (nessun backdrop scuro; la WebUI sotto resta cliccabile).
Menu a **categorie** a sinistra + contenuto a destra.

| Categoria | Contenuto (riuso attuale) |
|-----------|---------------------------|
| **General** | Self/harness: stato servizio, versione, capability (`renderSelf`) |
| **Models** | modelli disponibili (lista read-only) + modello **default** + **Compaction model** (dropdown → `config/routing.yaml`, ruolo `summarizer`) |
| **Providers** | CRUD provider (id/name/kind/url/key_env/models/local) |
| **Keys & Token** | keys summary/list + **API token mascherato** (`••••` + occhio + **copia**) |
| **MCP** | lista + **catalog** one-click + add manuale (env incluso) + test/save/reload |
| **Skills** | install da zip + lista installate (+ skill viewer) |
| **Rules** | Workspace (path, set default, use) + Rules global/project (+ apri nell'editor) |
| **Tools & policy** | Runtime, Verifier, Best-of-N, Difficulty, Self-evolving + policy per-tool (ex pannello *config*) |

Persistenza: posizione/dimensione/stato/last-categoria in `localStorage` (`sf_settings_*`).

## 5. Mappatura funzioni → nuova sede (prova "niente perso")

Ogni funzione attuale ha una destinazione:

- Topbar: **ctx meter** → resta; **compact** → resta (topbar) *e* copia in Inspector/Context;
  **model ▾** → resta; **sandbox / server / feed-dot** → restano; **▤** → resta;
  **▥** → ora mostra/nasconde l'Inspector; **⌘K** → resta; **+ ⚙** → apre la finestra Impostazioni.
- Palette (⌘K): comandi aggiornati → "New session", "Compact", "Apri Inspector §<sezione>",
  "Apri Impostazioni → <categoria>".
- Dialoghi invariati: new session, folder picker, skill viewer, diff view, image viewer, CoT drawer.
- Chat/composer/slash/tabbar mobile: invariati.
- Pannelli rail *graph/context/approvals/files/feed* → **Inspector**.
- Pannelli rail *config/settings/mcp/skills/rules* → **Impostazioni**.

## 6. Sicurezza

- **API token** mostrato mascherato di default; occhio per rivelare; **copia** negli appunti.
- Nessun segreto nuovo nel repo (restano in `localStorage` / file `.local.yaml` esterni).

## 7. Strategia di implementazione (fasi, basso rischio)

Riuso massimo di id e funzioni esistenti per **non riscrivere la logica**:

1. **Fase 1 — Finestra Impostazioni**: creare la finestra mobile; spostare dentro i blocchi
   `<section>` di config/settings/mcp/skills/rules **mantenendo gli id**; rimuovere quelle tab dal rail;
   aggiungere la categoria **Models** con il controllo **Compaction model** (endpoint nuovo che scrive `routing.yaml`).
2. **Fase 2 — Inspector**: trasformare il rail in colonna a sezioni; riusare i blocchi
   graph/context/approvals/files/feed come sezioni richiudibili; aggiornare `openPanel`→`focusSection`.
3. **Fase 3 — Token + polish**: mascheramento token con copia/occhio; grafica; palette; test.

## 8. Test / verifica

- Aggiornare `tests/v125_files_editor.py`, `tests/v150_webui_editor.py`.
- Nuovi check: presenza finestra Impostazioni + 8 categorie; Inspector + 5 sezioni; token mascherato
  (nessun token in chiaro nel DOM di default); controllo **Compaction model**; nessuna tab vecchia rimasta.
- Verifica browser reale (chrome-devtools): apri/chiudi/sposta la finestra; sezioni inspector;
  nessuna regressione sui dialoghi (new session, diff, skill viewer).

## 9. Non in scope (onestà)

- Pannelli "web search results" e "files read": **non esistono dati** nel backend oggi → non li invento.
  Andranno aggiunti quando (e se) il dato esiste.

## 10. Rischi

- `index.html` è un monolite (~2700 righe) → le fasi riducono il rischio; ogni fase testata e committata.
- Wiring `openPanel` usato dalla palette e dalle session-switch → aggiornare con cura e testare.
