# `src/` — the shipped application

`src/sparkforge/` is the SparkForge application package. **This is what ships**: it is
what `run.sh` / `python3 server.py` import, what the tests under `tests/` exercise, and
the only package installed at runtime.

The sibling `src2/` is **not** part of the application — it is the optional, detachable
"Bridge" (formerly Orbit) beta console, reached only through two guarded hooks in
`src/sparkforge/server.py`. It can be deleted at any time without touching the app; see
`src2/README.md`.
