## What & why

<!-- One or two sentences: the change and the reason. Link the issue it closes. -->

Closes #

## How

<!-- The approach, and any trade-off you made. -->

## Checklist

- [ ] One logical change; commit messages are typed (`feat:` / `fix:` / `docs:` / …)
- [ ] Deterministic test added/updated under `tests/acceptance/v<NNN>_<topic>.py`
- [ ] `bash tests/battery.sh` is **GREEN**
- [ ] Core stays **stdlib-only** (no new `pip` dependency in `src/sparkforge/`)
- [ ] Cross-platform preserved (no POSIX assumption leaked out of `osutil.py`)
- [ ] No secrets; `.env` stays gitignored
- [ ] `CHANGELOG.md` `## [Unreleased]` updated for any user-visible change
- [ ] Docs updated if behaviour or the API changed

## Evidence

<!-- A number, not a belief: test count, HTTP status, file field, screenshot. -->
