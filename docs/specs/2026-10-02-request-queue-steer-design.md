# Design — code / steer delle richieste

Data: 2026-10-02 · Tema: JAG-119 (#3) · Stato: **spec, non implementato**

## Problema (feedback utente)

Mentre l'agente lavora non si può aggiungere una richiesta: oggi o si aspetta o si
interrompe. Un IDE agentico moderno permette di **accodare** ("queue") o **pilotare**
("steer") una richiesta mentre la run è in corso, vedendola, modificandola o
cancellandola prima che venga eseguita.

## Modello

Due modalità, selezionabili dal composer:

- **queue** — il messaggio viene messo in coda e parte **dopo** che il turno corrente
  è finito (comportamento FIFO).
- **steer** — il messaggio viene iniettato nel **turno in corso**: l'agent loop lo legge
  al prossimo giro (boundary = tra un'iterazione e la successiva), così la richiesta
  corregge la rotta senza ripartire.

Seed implicito: una richiesta inviata mentre lo stream è attivo va in coda (mai persa).

## Dati

`session["queue"] = [ {"id","text","mode":"queue|steer","created","status":"pending|consumed|cancelled"} ]`
persistito nel file sessione; sopravvive al reload.

## API (api_v02)

- `GET  /api/queue?session=<id>` → lista + contatore.
- `POST /api/queue {session, text, mode}` → accoda (mode default `queue`).
- `PATCH /api/queue {session, id, text}` → **riedita** una voce pending.
- `DELETE /api/queue?session=&id=` → **cancella** una voce pending.
- `POST /api/queue/reorder {session, ids}` → riordino opzionale.

## Motore

- `chat_stream_gen` / `agent_run_v2`: a ogni iterazione, se esiste una voce `steer`
  pending, la si consuma (status→consumed) aggiungendola ai messaggi; le voci `queue`
  restano finché il turno non termina, poi il turno successivo le preleva in ordine.
- La UI, su `chat.user`/queue.update, aggiorna la lista in tempo reale.

## WebUI

- Toggle `queue | steer` accanto a `send` (persistito in localStorage).
- Pannello coda sopra il composer: `▤ 2 in coda`, ogni riga con ✎ (riedita) e ✕ (cancella),
  stato pendente/consumato.
- Badge/contatore; `send` non bloccato durante lo streaming (oggi è disabilitato).

## Criteri di accettazione

- Con uno stream attivo, inviare con mode=queue mostra la voce nella lista e la esegue dopo.
- Con mode=steer, l'agent loop incorpora il testo al giro successivo (evento `agent.steer`).
- Riedit/cancella funzionano su voci pending; persistono al reload.
- Nessuna richiesta persa se si invia durante lo stream.

## Sforzo stimato

M (server: coda per-sessione + consumo nel loop; WebUI: pannello + toggle + edit/delete).
