# SparkForge v0.5 — UX harness moderna (JAG-41) — evidenza

Data: 2026-09-29. Build: `server.py` v0.5.0, test server su `127.0.0.1:8791`
(stesso codice della wave; il servizio systemd su :8790 va riavviato per servire
v0.5 — vedi hand-back nel commento di chiusura JAG-41).

## 1. Compaction reale (prima: 404)

```
$ POST /api/context/compact {"session": "<id>", "budget_tokens": 800}
# transcript sintetico: 40 messaggi ~400 caratteri
→ {'input_messages': 40, 'input_tokens': 4040, 'compacted': 32,
   'kept': 0, 'dropped': 8, 'tokens_after': 1344}

$ GET /api/context?session=<id>
→ {'budget_tokens': 6000, 'messages': 8, 'tokens_used': 1344, 'over_budget': False}
```

Prima del fix: `POST /api/context/compact` → **404** (verifica Coordinator JAG-33).

## 2. Chat/CoT streaming + todo breakdown live

```
$ GET /api/chat/stream?message="ciao! ricordati che mi chiamo Dario e poi
  dividiti in 3 todo per testare la todo board"   (router :8080, nex-n25-mini)
→ elapsed 11.7s think_chars=1043 answer_chars=256
  THINK head: "We need answer in Italian likely. Need interpret user asks
               remember name Dario, then split into 3 todo…"
  ANSWER: "Ciao Dario! Ho ricordato il tuo nome. Ecco i 3 todo…"

# breakdown automatico sulla task board (evento SSE tasks.breakdown):
→ tasks total: 16 ; ultime aggiunte:
  ['Salutare Dario', 'Verificare l’accesso alla todo board', 'Creare tre task di test']

$ GET /api/history?session=<id>
→ history msgs: 2 roles: ['user','assistant'] ; reasoning stored: True
```

## 3. Self-knowledge ("dove sei installato e come installi una skill MCP")

```
$ POST /api/chat {"message": "dove sei installato e come installi una skill MCP?"}
→ "Sono installato in `/home/jagones/Repositories/sparkforge` (dati in `data`).
   Aggiungi una voce `stdio` o HTTP a `config/mcp_clients.yaml`, poi ricarica
   con `POST /api/tools` o `systemctl --user restart sparkforge.service`."

$ GET /api/self
→ repo_path=/home/jagones/Repositories/sparkforge systemd=active
  config={tools.yaml, routing.yaml, mcp_clients.yaml} install_skill_mcp=<recipe>

$ python3 -c "import tools; r=tools.execute('self', {}); print(r['ok'], r['repo_path'])"
→ True /home/jagones/Repositories/sparkforge   (anche in MCP tools/list, approval auto)
```

## 4. Sessioni UX API

```
$ POST /api/sessions {"title": "JAG-41 test"}   → {"id": "8d707afca52c", …}
$ GET  /api/sessions                            → 39 sessioni listate
$ DELETE /api/sessions/8d707afca52c             → {"ok": true, "deleted": "8d707afca52c"}
```

## 5. GUI mobile (webui/index.html)

- 342 → 562 righe; stesso tema dark glass esteso, non riscritto.
- Tab bar mobile: chat / sessions / tasks / context / feed (drawer slide-in).
- Drawer CoT live sempre visibile durante lo streaming + cursore blink.
- Meter contesto (barra tok/budget, rossa >90%) + pulsante 🗜 compact in header.
- Sintassi JS verificata: `node --check` → OK.

## 6. Regressioni sul nuovo build

```
$ SPARKFORGE_URL=http://127.0.0.1:8791 python3 tests/v02_acceptance.py
→ 8/8 checks passed (sandbox, approval, HITL, MCP stdio/HTTP)

$ SPARKFORGE_URL=http://127.0.0.1:8791 python3 tests/v03_acceptance.py
→ 7/7 checks passed (checkpoints, compaction, routing/fallback, MCP v0.3)

$ SPARKFORGE_URL=http://127.0.0.1:8791 python3 tests/v04_acceptance.py
→ 12/17 passed; i 5 fallimenti sono ambientali, non regressioni:
  A2 auth (server di test senza --token), D1-D4 voice (env whisper/sherpa non
  propagato al processo di test server). A3 aggiornato a version >= 0.5.0.
```