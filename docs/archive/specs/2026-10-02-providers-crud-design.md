# 2026-10-02 — Provider/LLM aggiungibili dall'utente, con form (JAG-112)

## Problema

`config/providers.yaml` è **statico**: la lista di provider e modelli non è
modificabile da UI/API. L'utente non può aggiungere un LLM o un endpoint senza
editare a mano il file (e rischia di mettere segreti nel repo).

## Obiettivi

1. Aggiungere/modificare **provider** e **modelli** e impostare il **default**
   via API e da un **form** nella WebUI.
2. Nessun segreto nel repo: un provider nomina solo `api_key_env` (NOME della
   variabile). Le aggiunte utente finiscono in un **overlay locale gitignorato**
   `config/providers.local.yaml`, mai nel file base versionato.
3. Il file base resta intatto; l'overlay si sovrappone (merge per id).

## Design

### `providers.py` (motore unico)
- `LOCAL_CONFIG = config/providers.local.yaml` (override `SPARKFORGE_PROVIDERS_LOCAL`).
- `load()` = **merge(base, local)** con cache su `(mtime_base, mtime_local)`:
  - provider per `id`: i campi scalari locali **sovrascrivono** il base;
  - `models`: **unione** per id (il locale aggiorna/estende, senza duplicare);
  - `disabled: true` su provider o modello = esclusione (tombstone per i base);
  - `default` locale vince.
- CRUD (scrivono SOLO l'overlay, con scrittura atomica):
  - `upsert_provider(spec)`, `remove_provider(pid)`,
  - `add_model(pid, model_id, context_length=None)`, `remove_model(pid, mid)`,
  - `set_default(ref)`, `reload()`.
- **Validazione**: `id` `^[a-z0-9][a-z0-9._-]*$`; `kind` in whitelist; `base_url`
  http/https; `api_key_env` deve essere un **nome** di variabile
  (`^[A-Z][A-Z0-9_]*$`) — un valore che sembra una chiave viene **rifiutato**.
  Ritorna `{"ok": bool, "error"?: str, ...}`.

### `api_v02.py`
Helper (testabili senza HTTP come JAG-109): `provider_upsert(body)`,
`provider_remove(pid)`, `provider_add_model(body)`, `provider_remove_model(pid, mid)`,
`provider_set_default(body)`, `provider_reload()`. Branch HTTP:
- `POST /api/providers` (upsert), `DELETE /api/providers?id=`,
  `POST /api/providers/models`, `DELETE /api/providers/models?provider=&model=`,
  `POST /api/providers/default`, `POST /api/providers/reload`.

### WebUI
Nuova tab **Providers** (come MCP/Skills): lista (provider, kind, endpoint, modelli,
default) + form per aggiungere/modificare un provider (id, nome, kind, base_url,
api_key_env, modelli) + set default + elimina. Costruita con la DOM API.

## Test (TDD — `tests/v112_providers_crud.py`)
- **P1** upsert nuovo provider → in catalogo + scritto nell'overlay.
- **P2** override di un campo di un provider base → base intatto.
- **P3** add_model / remove_model su provider base (tombstone del modello).
- **P4** remove_provider: solo-locale rimosso; base → disabilitato ma base intatto.
- **P5** set_default → `default_ref()` aggiornato.
- **P6** validazione: id/base_url/api_key_env non validi → rifiutati.
- **P7** nessun segreto scritto: l'overlay contiene il NOME della var, mai il valore.
- **P8** helper API (`provider_upsert`/`provider_remove`/...) presenti e coerenti.

## Non-obiettivi
- Nessuna cache/verifica live del modello remoto (fuori scope).
- Nessuna modifica a `routing.yaml` (già editabile via `/api/routing`).
