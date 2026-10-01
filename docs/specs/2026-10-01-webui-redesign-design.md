# SparkForge WebUI Redesign — Design

- **Data:** 2026-10-01
- **Stato:** approvato (design) — pronto per il piano di implementazione
- **Autore:** Giovanni J. Agones / jagones84
- **Repo:** sparkforge
- **Ambito:** solo frontend WebUI (`webui/index.html`). Nessuna modifica al backend o all'app mobile.

## 1. Contesto

La WebUI è un **singolo file** `webui/index.html` (~40 KB) servito da `server.py` sulla porta `8790`
(vedi `Handler.do_GET`, `WEBUI_DIR`). È un pannello funzionante ma visivamente datato: tab bar
confusa (`AL WEBUI / MISC / USAGE / KNOWLEDGE / REPOS+MODELS`), enormi spazi vuoti, plan panel che
ripete lo stesso step ("say hello" ×9), nessun pannello di contesto, tool result piatti.

L'app mobile **SparkPulse** (Kotlin/Compose) è già più matura: rail a pannelli
(`Graph / Config / Self / Settings`), tool card interattive (`ForgeToolCard`), selettore modello,
chip (`⚡ fs+shell AUTO`, `↻ ricarica`), grafo task con dipendenze, visione della sessione con
`titolo · id · n msg`.

## 2. Obiettivo

Portare la WebUI a qualità "desktop IDE" con **parità funzionale** rispetto ai pannelli SparkPulse,
**senza introdurre build step o framework** (resta un file autonomo servito dal backend attuale).

## 3. Non-obiettivi (YAGNI)

- Non riscrivere backend/API: si consumano gli endpoint esistenti.
- Non introdurre bundler, npm, React/Vue o toolchain di build.
- Non toccare l'app mobile SparkPulse.
- Non implementare viste che il backend non espone già.

## 4. Gap da chiudere (selezione utente: tutti e 5)

| # | Gap | Esito atteso |
|---|-----|--------------|
| A | Pannelli laterali mancanti (Graph, Config, Self, Settings, Approvals) | Rail contesto a tab |
| B | Tool card & thinking live | Card interattive + thinking streaming |
| C | Estetica / gerarchia visiva | Design system coerente, top bar, densità |
| D | Layout & densità | Griglia 3 colonne adattiva |
| E | Bug visibili | Plan non duplicato, sessioni filtrabili, stato sincronizzato |

## 5. Direzione scelta — A · Desktop IDE (3 colonne)

Scartate: *B Chat-first* (troppo scrolling), *C Mission Control* (troppo rumore/complessità).
Si adotta **A**, arricchita dalla **command palette ⌘K** mutuata da B.

```
┌──────────────────────────────────────────────────────────────┐
│ ◈ SparkForge   model ▾   ctx meter   sandbox   ● server  ⌘K   │  top bar
├───────────┬────────────────────────────────┬─────────────────┤
│ SESSIONI  │            CHAT                │    CONTESTO      │
│ ricerca   │  messaggi + tool card          │ [Graph][Config]  │
│ + nuova   │  + thinking live               │ [Self][Settings] │
│ elenco    │  ─────────────────────────     │ [Approvals]      │
│ filtro    │  input  [send] [⚡ agent]      │  pannello attivo │
└───────────┴────────────────────────────────┴─────────────────┘
```

- Colonna sinistra: **200px**. Centrale: **flex**. Destra: **238px**.
- Sotto **1100px** la rail destra diventa **drawer** sovrapposto; sotto **820px** anche la colonna
  sessioni diventa drawer (comportamento mobile-friendly).

## 6. Design system

- **Colori:** accento viola `#8b7bf0`; `you` blu `#8fb6ff`; ok verde `#4ecb8d`; deny rosso `#ef6461`;
  info ciano `#5ac8fa`; sfondi `#0f1219` / `#121722` / `#161b25`; bordi `#2b3140` / `#1e2431`.
- **Tipografia:** scala 11 / 13 / 16 px; monospace per path/args/output.
- **Spacing:** base 4px (4/8/12/16); angoli 6–12px; ombre tenui.
- **Componenti:** chip, badge di stato, meter, card, tab, drawer, tool card.

## 7. Top bar

Logo + nome; **chip modello** (▾ apre selettore, da `/api/providers` + `/api/models`); **meter ctx**
(da `/api/context`); **sandbox** (`/api/selfcheck` o `/api/sandbox`); **badge server** (`● ok` da
`/api/status`); pulsante **⌘K**.

## 8. Rail contesto (pannelli)

Tab con pannello a scomparsa, ognuno mappato a un endpoint esistente:

| Pannello | Fonte API |
|----------|-----------|
| Graph | `GET /api/runs/<id>/graph` + `POST /api/runs/<id>/graph/nodes` |
| Config | `GET/POST /api/tools` (allowlist, approval) |
| Self | `GET /api/self`, `GET /api/selfcheck` |
| Settings | `GET /api/providers`, `/api/models`, `/api/routing` |
| Approvals | `GET /api/approvals`, `POST /api/approvals/<id>` |

Stato vuoto esplicito quando non c'è un run/sessione attiva.

## 9. Chat

- Messaggi con etichetta ruolo (`YOU` / `FORGE`), **markdown** renderizzato.
- **Tool card interattive**: stato (✅/⛔), nome tool, args, risultato espandibile, durata; errore in
  rosso, blocco deny evidenziato.
- **Thinking live** streaming, collassabile, con indicatore attivo `◉ thinking…`.
- Input con `send` + toggle `⚡ agent`; invio con Enter, shift+Enter a capo.

## 10. Sessioni + ⌘K

- Ricerca testuale; filtri "nascondi vuote" / "solo con tool"; riga con **titolo · id · n msg · quando**;
  azione elimina.
- **Command palette ⌘K**: salto sessione, nuova sessione, apri pannello, cambia modello, compatta contesto.

## 11. Bug da correggere

1. **Plan duplicato** ("say hello" ×9): deduplica/normalizza gli step prima del render.
2. **Sessioni spazzatura**: filtri + ordinamento per attività; raggruppa le vuote.
3. **Stato non sincronizzato**: riuso di `/api/feed` (SSE) per riflettere cambi di sessione/plan/task.

## 12. Approccio tecnico

- **Un solo `index.html` autonomo**, zero build. Struttura interna ordinata in sezioni commentate
  (design tokens → layout → componenti → stato → trasporto SSE → render).
- **Token in UI:** campo impostazioni che salva il bearer in `localStorage` e lo applica a fetch **e**
  `EventSource` (`?token=`), eliminando la necessità di `?token=` nell'URL.
- Riuso degli stessi endpoint/SSE già usati dalla UI attuale e da SparkPulse.
- Nessuna modifica a `server.py` prevista; se emergesse la necessità di servire asset separati, si
  valuterà a parte (fuori scope).

## 13. Fasi

1. **Struttura + estetica**: 3 colonne, design system, top bar, responsive.
2. **Pannelli contesto**: rail a tab con i 5 pannelli.
3. **Chat**: tool card interattive + thinking live + markdown.
4. **Sessioni + ⌘K**: ricerca, filtri, palette.
5. **Bug**: plan duplicato, sessioni, sincronizzazione via feed.

## 14. Criteri di accettazione

- [ ] Layout a 3 colonne visibile su desktop ≥1100px; drawer su viewport ridotta.
- [ ] I 5 pannelli aprono e mostrano dati reali dagli endpoint indicati.
- [ ] I tool result compaiono come card espandibili con stato ✅/⛔.
- [ ] Il thinking è live e collassabile.
- [ ] La ricerca sessioni filtra e "nascondi vuote" funziona.
- [ ] ⌘K apre la palette con le azioni richieste.
- [ ] Il plan non ripete più step identici.
- [ ] La UI si aggiorna agli eventi del feed senza refresh manuale.
- [ ] Il token si configura in UI (nessun `?token=` necessario nell'URL).
- [ ] Nessuna regressione sulle funzioni esistenti (chat, sessioni, plan, agent run).

## 15. Rischi

- **Dimensione del file unico**: mitigato da struttura a sezioni; se cresce troppo, valutare split CSS/JS.
- **Auth SSE su `EventSource`**: gestito con `?token=` + campo UI.
- **Fedeltà ai dati delle API**: ogni pannello va validato contro la risposta reale, non assunta.
