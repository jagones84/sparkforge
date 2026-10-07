# SparkForge — Skills: install via zip + uso con `/` — Design

- **Data:** 2026-10-02
- **Stato:** approvato (design) — pronto per il piano di implementazione
- **Autore:** Giovanni J. Agones / jagones84
- **Repo:** sparkforge
- **Ambito:** engine skills ([skills.py](file:///z:/Repositories/sparkforge/skills.py)), API HTTP ([api_v02.py](file:///z:/Repositories/sparkforge/api_v02.py)), inject lato server in [server.py](file:///z:/Repositories/sparkforge/server.py), WebUI ([webui/index.html](file:///z:/Repositories/sparkforge/webui/index.html)). L'app mobile e la CLI beneficiano della stessa API senza modifiche (l'inject è lato server).

## 1. Contesto

Le skill sono directory `skills/<categoria>/<nome>/SKILL.md` scoperte automaticamente da
[skills.py](file:///z:/Repositories/sparkforge/skills.py) (cache su `mtime` della root `skills/`).
L'agente le usa col tool `skills` (`action:list` / `action:read`), e la lista è iniettata nel system
prompt (`skills_context`, JAG-79). Esiste già l'ecosistema clawhub: alcune skill contengono
`.clawhub/origin.json`, `_meta.json`, `skill-card.md`, ma **non esiste alcuna API HTTP** per
elencare/installare/rimuovere skill, né un modo per l'utente di caricarne una.

Nella chat l'unico comando `/` è `/goal` (gestito client-side, JAG-92). Manca un `/` che mostri le
skill e le renda eseguibili in un colpo.

## 2. Obiettivo

1. **Installare una skill** caricando un archivio **zip** (solo zip) dalla WebUI/API: il server lo
   estrae in una categoria locale dedicata `skills/local/<nome>/`.
2. **Elencare / leggere / rimuovere** le skill via API, con distinzione locale vs sistema.
3. **Usare una skill dalla chat**: digitando `/` compare la lista; scegliendone una, il **server**
   inietta la `SKILL.md` nel prompt di quel turno (one-shot), così l'agente la esegue subito.

## 3. Non-obiettivi (YAGNI)

- Niente upload di singolo `SKILL.md` (deciso: solo zip).
- Niente registry remoto (no download da clawhub.ai): solo upload locale.
- Niente modifica all'app: erediterà endpoint e inject senza codice nuovo.
- Niente riscrittura di `skills.py` in moduli più piccoli: si estende con funzioni mirate.

## 4. Roadmap generale (tutti i punti richiesti, registrati qui)

| # | Sottoprogetto | Stato |
|---|---------------|-------|
| **1** | **Skills: install via zip + uso con `/`** | **questa spec** |
| 2 | MCP: import dell'intero `mcp.json` (`{"mcpServers":{...}}`) su `POST /api/mcp/import` + import da WebUI | dopo |
| 3 | Allegati in chat: attach di foto/PDF/file di ogni tipo a un messaggio (upload + riferimento nel prompt + rendering) | dopo |
| 4 | Allegati testuali `.md`/testo | assorbito in 3 (probabilmente non serve separato) |

L'ordine di esecuzione è: 1 → 2 → 3 (deciso dall'utente).

## 5. Architettura — motore unico

Il principio resta quello dei sottoprogetti precedenti: **la logica sta nel server**, i client
(WebUI/app/CLI) chiamano gli stessi endpoint e non replicano derivazioni.

```
WebUI  ──┐
App    ──┼──►  API HTTP (/api/skills*)  ──►  skills.py (engine)  ──►  skills/local/<nome>/
CLI    ──┘              │
                        └──►  /api/chat: inject one-shot della SKILL.md nel prompt del turno
```

## 6. Engine — estensioni a `skills.py`

Nuove costanti/funzioni (resta l'unica fonte di verità per la scoperta delle skill):

- `LOCAL_CATEGORY = "local"`, `LOCAL_DIR = os.path.join(SKILLS_DIR, "local")`
  (override d'ambiente `SPARKFORGE_SKILLS_LOCAL_DIR` per i test).
- `list_skills()` già scansiona tutte le categorie: si aggiunge il flag **`local: bool`**
  (`category == LOCAL_CATEGORY`) a ogni voce. La cache su `mtime` di `SKILLS_DIR` copre anche
  `local/` (è una sottocartella) — nessuna invalidazione extra necessaria.
- `install_zip(data: bytes, name: str|None, overwrite: bool=False) -> dict`
  estrae l'archivio in `skills/local/<nome>/` (vedi §8 sicurezza).
- `remove(name: str) -> dict` rimuove **solo** skill in categoria `local` (le skill di sistema e i
  symlink non sono mai toccabili da qui).
- `is_local(name) -> bool` helper.
- `get_skill(name)` invariato (già legge qualsiasi categoria).

**Nome skill**: priorità `query ?name=` → frontmatter `name:` della `SKILL.md` → stem del file zip.
Sanificato con `^[a-z0-9][a-z0-9._-]*$` (lowercase). Nome non valido → errore 400.

## 7. API HTTP (in `api_v02.py`)

| Metodo | Path | Corpo | Risposta |
|--------|------|-------|----------|
| GET | `/api/skills` | — | `{skills:[{name,category,title,description,local}], count, local_dir}` |
| GET | `/api/skills/<nome>` | — | `{ok,name,category,title,description,local,content}` / 404 `{error}` |
| POST | `/api/skills/install?name=<n>&overwrite=1` | **raw `application/zip`** | `{ok,name,category:"local",files,bytes}` / 400 `{error}` |
| DELETE | `/api/skills/<nome>` | — | `{ok,name}` / 400 `{error}` (non locale o inesistente) |

- Upload **raw** (non multipart): stesso schema già in uso per `/api/voice/stt` (raw audio). La WebUI
  invia il `Blob` del file con `Content-Type: application/zip`. Evita il parsing multipart con la
  stdlib.
- `POST` pubblica l'evento feed `skills.install`; `DELETE` pubblica `skills.remove` (visibilità UI).
- **Precedenza route**: si matcha esplicitamente `/api/skills/install` **prima** della rotta
  parametrica `/api/skills/<nome>`, così una skill chiamata "install" non intercetta la POST.
- Errori sempre JSON `{error}` con 400/404, mai eccezioni grezze.

## 8. Sicurezza estrazione zip (default non negoziabili)

- **Zip-slip**: ogni entry è normalizzata; si rifiuta path assoluto o contenente `..`. Dopo
  l'estrazione si verifica che `os.path.realpath(dest)` sia dentro `realpath(target)`.
- **Symlink**: le entry con bit symlink sono **rifiutate** (evita escape dall'albero).
- **Cap**: `≤ 20 MB` compresso, `≤ 60 MB` totale decompresso, `≤ 500` file. Override per i test via
  `SPARKFORGE_SKILL_MAX_ZIP` / `SPARKFORGE_SKILL_MAX_UNZIP` / `SPARKFORGE_SKILL_MAX_FILES`.
- **Top-dir stripping**: se tutte le entry condividono una singola dir radice (es. `my-skill/…`),
  viene rimossa → il contenuto finisce direttamente in `skills/local/<nome>/`.
- **SKILL.md obbligatorio**: dopo lo strip, se `SKILL.md` non è nella radice della skill → 400 e
  l'estrazione viene annullata (nessun residuo).
- **Overwrite**: consentito **solo** con `?overwrite=1` e **solo** su skill locali. Mai su skill di
  sistema. Senza flag, collisione → 400.
- **Atomicità**: estrazione in una dir temporanea dentro `skills/local/`, poi `os.replace` verso la
  destinazione finale; su errore si elimina il temporaneo.

## 9. Uso in chat — `/`

- Il **client** (WebUI) mostra un dropdown delle skill quando l'input inizia con `/`, filtrando per
  prefisso. Selezione → inserisce `/nome `. Invio → invia il testo così com'è.
- Il **server**, in `/api/chat` (assemblaggio già centralizzato da JAG-100), riconosce un messaggio
  che inizia con `/<nome>` dove `<nome>` è una skill nota e:
  1. **non** modifica la history salvata (resta `/nome testo`);
  2. inietta in modo **transitorio** un blocco `SKILL.md` (+ direttiva "segui questa skill") solo nel
     prompt inviato al modello per quel turno.
- `/goal` resta invariato (gestito client-side con `mode=goal`).
- `/x` sconosciuto → trattato come testo normale (nessun cambiamento di comportamento).

**Perché lato server**: app, WebUI, CLI e subagent ottengono l'inject gratis, nessuna logica
duplicata nei client.

## 10. WebUI

- **Pannello Skills** (nuova tab nel rail, come il pannello MCP di JAG-108): input file
  (`accept=.zip`), campo nome (precompilato dallo stem del file), pulsante *installa*, riga risultato;
  lista con badge **🏠 sistema / 🟢 locale**, titolo, descrizione, pulsante 🗑 (solo locali, riusa
  `confirmDelete` di JAG-105).
- **Autocomplete `/`** nella barra chat: dropdown costruito con DOM API (niente librerie, come il
  resto del file).

## 11. Errori e logging

- Ogni endpoint valida prima di agire (pre-flight): nome, dimensione, presenza SKILL.md.
- `try/except` con messaggio JSON e log su stderr `[skills] …`.
- Estrazione fallita = nessuna modifica allo stato (dir temporanea rimossa).

## 12. Test (TDD) — `tests/v109_skills_install.py`

Scritti **prima** dell'implementazione, tutti in-process (engine) + uno sull'API e uno sull'inject:

| ID | Caso |
|----|------|
| S1 | install di uno zip valido → compare in `list_skills()` con `local:true` |
| S2 | zip senza `SKILL.md` (o con SKILL.md annidato oltre lo strip) → 400, nessun residuo |
| S3 | zip-slip (`../../evil`) → rifiutato, nulla scritto fuori da `skills/local/<nome>/` |
| S4 | entry symlink → rifiutata |
| S5 | oltre il cap (compresso e decompresso) → rifiutato |
| S6 | collisione senza `overwrite` → 400; con `overwrite=1` → ok |
| S7 | `overwrite` su skill di sistema → rifiutato |
| S8 | `remove` di skill locale → ok e sparisce; `remove` di skill non locale → rifiutato |
| S9 | `/nome testo` → il prompt assemblato per il turno contiene la `SKILL.md` (inject one-shot) |
| S10 | `GET /api/skills` elenca le skill con il flag `local` corretto |

Regressione: `tests/v071_skills_pmcp.py` deve restare verde (nessuna skill di sistema toccata).

## 13. Git

`skills/local/` è aggiunto a `.gitignore`: le skill caricate dall'utente **non** finiscono nel repo
(nessuno script/segreti committati), coerentemente con la regola del workspace.

## 14. Criteri di accettazione

- Si installa una skill caricando uno zip dalla WebUI; appare in `/api/skills` e nel pannello.
- Digitando `/` nella chat compare la lista; scegliendo una skill, l'agente ne segue la `SKILL.md`.
- Zip malevoli (zip-slip/symlink/oversize) sono rifiutati senza scrivere fuori dalla destinazione.
- Le skill di sistema restano intatte; `skills/local/` non è nel repo.
- `v109` verde al 100% + regressione `v071` verde.
