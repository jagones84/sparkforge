# Design — rifiniture UX WebUI + cartella di sessione

Data: 2026-10-02 · Temi: JAG-116 (#1, #2, #4) + JAG-117 (#5)

## Problemi (feedback utente, con screenshot)

1. **#1 selettore modelli illeggibile**: il pulsante in alto usa la classe `.pill`
   (`color: var(--dim)`) → testo del modello sbiadito.
2. **#2 tool card vuote**: espandendo una card (es. `write_todos`) il corpo è vuoto:
   `_apply_chat_todos` emetteva `tool.call` con `args={}` e `tool.result` senza `output`.
   Idem `update_todos`.
3. **#4 scroll che strappa**: `scroll()` forzava `scrollTop = scrollHeight` a ogni
   token → impossibile risalire mentre il modello scrive; nessuna freccia "torna giù".
4. **#5 sessione senza cartella**: il workspace era globale; aprendo una sessione non
   veniva chiesta la cartella; le sessioni esistenti non avevano alcuna cartella.

## Soluzioni

### #1 — leggibilità
`.model-btn` non eredita più il grigio: `color: var(--txt)`, `font-weight: 600`,
bordo/fondo accent, `max-width` con ellipsis.

### #2 — input/output nelle card
- `_apply_chat_todos`: `tool.call` con `args={"todos":[...]}`; `tool.result` con
  `args`, `output` = elenco `- [status] label`, oltre a `summary`.
- `_apply_chat_todo_updates`: idem con `args={"steps":[...]}` e `output` dei nodi cambiati.
- La WebUI già rende `input:`/`output:` quando presenti (`toolCard`/`updateToolCard`).

### #4 — scroll rispettoso + freccia
- `_stick` (true = incollato in fondo). `scroll()` auto-scrolla **solo** se `_stick`.
- Listener su `#log`: `_stick = _nearBottom()`; il pulsante `#jumpBtn` (flottante)
  compare solo se c'è overflow e non si è in fondo; click → torna in fondo.
- Aprendo una sessione `_stick = true` (si atterra sull'ultimo messaggio).

### #5 — ogni sessione ha una cartella
- `server.ensure_session_workspace(sess, ws=None)`: precedenza `ws` esplicito →
  cartella esistente → default globale. Ritorna True se cambia.
- `get_or_create_session(sid, title, workspace)`: pinna alla creazione e **backfilla**
  le sessioni esistenti al primo caricamento.
- `backfill_session_workspaces()` chiamata in `main()`: garantisce che ogni sessione
  salvata abbia una cartella.
- `/api/sessions/new?title=&workspace=`.
- WebUI: `+ new` apre un dialog (`#newSessDlg`) che **chiede la cartella** (prefill =
  default globale) e il titolo.
- Bug corretto: `rules.check_dir("")` restituiva la cwd (`abspath("")`); ora vuoto → None.

## Criteri di accettazione

- Il pulsante modello ha contrasto pieno; il dialog chiede la cartella.
- Una card `write_todos`/`update_todos` mostra input e output.
- Scorrere su durante lo streaming **non** viene annullato; appare la freccia ↓.
- Ogni sessione (nuova o esistente) ha `workspace`; `list_sessions` lo espone.
- Nessuna regressione (v107→v117).
