# compact nel Context · settings chiari · MCP stile Trae — design (2026-10-03)

## Motivation (richieste utente)
1. Il bottone **compact** deve stare nella sezione **Context** (non nella topbar).
2. I settings **Tools & policy** sono criptici ("N facile/medio/difficile", "soglia medio 0.35"): renderli
   comprensibili e spiegare a cosa serve ogni campo.
3. MCP come **Trae**: (a) aprire in editor il **file MCP finale** e modificarlo a mano; (b) incollare **solo lo
   snippet** del server da aggiungere. **Rimuovere** il form "command + args + env". Marketplace: fuori scope.

## Stato attuale (verificato)
- `#compactBtn` nella topbar (`index.html` L406); `compactNow()` lo referenzia per id.
- Tools & policy: 5 card in `#settingsWin .sw-cat[data-cat="tools"]` (L508-547), etichette brevi senza aiuto.
- MCP: form manuale `#mcpName/#mcpTransport/#mcpCommand/#mcpArgs/#mcpEnv/#mcpUrl/#mcpHeaders` (L621-647);
  modale `#mcpJsonWin` (paste+import, L798-811) con `applyMcpJson` che upserta via `POST /api/mcp/clients`.
- Persistenza: `mcp_client._load_local_doc/_save_local_doc` scrivono `config/mcp_clients.local.yaml`
  (o `.json`) con schema `{clients:{...}}`; `load_doc()` fonde base tracciata + locale.

## D1 — compact nel Context
- Spostare il markup di `#compactBtn` dalla topbar alla sezione `data-insp="context"` (sotto il card del
  contesto). **Id invariato** → nessuna modifica JS.

## D2 — Tools & policy comprensibile
- Per ogni card: `<b>titolo</b>` + **una frase** di spiegazione (`.remaining`).
- Ogni `<label>`/input: **etichetta in chiaro** (italiano semplice) + attributo `title` con la spiegazione
  estesa (tooltip). Nessun cambio di id, logica o salvataggio.
- Contenuti (esempi):
  - Runtime: continuazioni massime; giri senza progressi prima di fermarsi; limite di tempo per run (s);
    livelli di sub-agent.
  - Verifier: comando (es. `python3 -m pytest -q`) eseguito dopo le modifiche; si applicano solo se passa.
  - Best-of-N: N risposte generate, si tiene la migliore (numero di campioni, punteggio minimo 0..1).
  - Difficulty: N tentativi per fascia di difficoltà + soglie 0..1 che separano facile/medio/difficile.
  - Self-evolving: lunghezza/occorrenze minime per sintetizzare una skill, lunghezza massima, categoria.

## D3 — MCP stile Trae
### File canonico
- `config/mcp_clients.local.json` (gitignored) = **il tuo `mcp.json`**, formato `{"mcpServers": {name: {...}}}`.
- `mcp_client`:
  - `_load_local_doc()`: legge il `.json`; se contiene `mcpServers`, lo traduce in `clients` interno
    (`command/args/env` → stdio; `url/headers` → http; `enabled` opzionale, default True). Retro-compatibile:
    se esiste ancora `mcp_clients.local.yaml` viene letto (migrazione), ma i salvataggi vanno nel `.json`.
  - `_save_local_doc(doc)`: scrive `config/mcp_clients.local.json` in formato `mcpServers` (con `enabled`
    preservato in ogni server per il round-trip).
  - `load_doc()`: base tracciata (`mcp_clients.yaml`) + locale (tradotto). Merge by name come oggi.
- `status()` espone `path` assoluto del file locale (per aprirlo in editor).

### UI
- **Rimosso** il form "Add manually" (name/transport/command/args/env/url/headers/test/save).
- **✎ Edit mcp.json**: bottone che apre il file locale nell'**editor** (`SparkEditor.open(path)`), poi
  "reload all" per applicare.
- **⧉ MCP JSON**: modale esistente (incolla snippet → **append/upsert**, non rimuove). Testo aggiornato.
- **Catalogo**: `＋ add` installa subito i preset senza token; i preset che richiedono un token aprono il
  modale snippet precompilato con il server (l'utente inserisce il token e conferma).
- Lista client: `✎` apre il file nell'editor (non piu' il form); `🗑` rimuove.

## Error handling
- Snippet non valido → messaggio nel modale, nessuna scrittura.
- File locale mancante → creato al primo salvataggio; `load_doc` ritorna i soli preset base.
- Editor non disponibile → fallback: apri il modale MCP JSON.

## Testing
- `tests/v157_compact_mcp_clarity.py`: statici (compact nel Context; titoli/frasi/tooltip tools; form rimosso;
  bottoni Edit/MCP JSON; `_save_local_doc` scrive `.json`; `mcpServers` nella load) + **live** (POST
  `/api/mcp/clients` con uno snippet, verifica che `config/mcp_clients.local.json` contenga `mcpServers`,
  poi rimozione).
- Regressione: v108 (MCP manage), v113 (settings), v129, v152 (MCP JSON).
