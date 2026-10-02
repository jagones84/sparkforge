# 2026-10-02 — WebUI: sessioni per uso, tool card piene, picker modelli, chiavi (JAG-113)

## Problemi (evidenza dal codice)

1. **Sessioni**: `list_sessions()` ordina per `created` e non espone l'ultimo
   utilizzo; nella barra non c'è nessun "3 min"/"15h".
2. **Tool card vuote**: `tool.result` (SSE) pubblica solo `tool, ok, inline`
   ([server.py](file:///z:/Repositories/sparkforge/server.py)) — **niente `args`
   né `output`** → `updateToolCard` non ha cosa mostrare. Su ricarica invece il
   payload arriva dai `tool_cards` persistiti (il live no).
3. **Picker modelli**: è una `<select>` nativa con voci `"… (not loaded)"` → il
   menu a tendina è brutto e non raggruppa i modelli caricati.
4. **Chiavi**: non c'è un posto in UI che dica dove mettere le API key
   (Brave/Tavily/GitHub…). Oggi vivono in `.env` / `~/.hermes/.env` (gitignorati) e
   i provider/MCP le referenziano per **nome** (`api_key_env`, `${VAR}`).

## Obiettivi

1. Sessioni ordinate per **ultimo utilizzo**, con etichetta relativa in basso a
   destra ("ora", "3 min", "15 h", "2 g").
2. Le tool card mostrano **input (args)** e **output** (troncati).
3. Picker modelli **custom**: pulsante + pannello, modelli caricati in cima, con ✓.
4. Pannello **Keys** in sola lettura: quali variabili servono, dove sono attese e
   se sono **impostate** (mai il valore).

## Design

### `server.py`
- `_rel_time(ts) -> "ora"|"N min"|"N h"|"N g"`.
- `list_sessions()`: aggiunge `updated` (max di created / ultimo msg / ultima tool
  card), `age` (`_rel_time`) e ordina per `updated` desc.
- `_trunc(s, n)`: tronca con ellissi.
- `_tool_event(tool, ok, args=None, output="", **extra)`: payload unico della card.
- I due `on_event("tool.result", …)` del chat-loop passano `args` + `output`
  (troncati da `_trunc`), `exit_code`, `backend`.
- `keys_status()`: aggrega i nomi da `providers` (`api_key_env`) e da
  `mcp_client` (`${VAR}` negli header) con `set` = variabile presente in env.
  Route `GET /api/keys`.

### WebUI (`webui/index.html`)
- **Sessioni**: riga con l'`age` a destra (nuovo campo server, nessuna logica locale).
- **Tool card**: `toolCard(tool, args)` riempie `tc-args`; `updateToolCard` mostra output.
- **Picker modelli**: pulsante `#model-btn` + pannello `#modelMenu` (custom),
  raggruppato: caricati prima, ✓ + badge.
- **Tab Keys**: lista `env` (🟢 impostata / 🟠 mancante) + "dove" + percorso `.env`.

## Test (TDD — `tests/v113_webui_polish.py`)
- **R1** `_rel_time` (ora / min / h / g).
- **R2** `list_sessions` espone `updated`+`age` e ordina per ultimo utilizzo.
- **T1** `_tool_event` include `args` e `output` troncati.
- **K1** `keys_status` elenca i nomi (`api_key_env`, `${VAR}`) con `set` booleano,
  **mai** il valore.

## Non-obiettivi
- Nessuno storage di segreti nel repo (resta `.env`).
- Nessuna modifica al motore di routing.
