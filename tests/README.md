# tests/ — how to test Longrun

Everything is standard-library Python. No framework, no network, no model needed
for the battery. One command, one exit code.

## Run

```bash
bash tests/battery.sh          # all acceptance tests, isolated, deterministic (the gate)
bash tests/mega_test.sh        # the full ladder: ruff + mypy + bandit + battery + hypothesis + mutmut
bash tests/nightly/mega.sh     # 8h overnight loop, safe autofix gated by the battery
python3 tests/acceptance/v310_agent_turn_delivery.py   # one test
pytest tests/properties/       # Hypothesis property tests
```

## Layout

| Dir | Purpose | Rule |
|-----|---------|------|
| `acceptance/` | the **live battery** `v140..v343` | auto-discovered by `battery.sh`; add new tests here |
| `legacy/` | frozen history `v02..v176` | do not add |
| `live/` | needs a running server | run by hand |
| `nightly/` | overnight loop + status helpers | see `mega.sh`, `start.sh` |
| `properties/` | Hypothesis tests over pure logic | |
| `e2e/` | Node tester-army project | gitignored, kept local |

## Isolation

`battery.sh` points every `LONGRUN_*` var at a throwaway `mktemp` dir and sets a
fresh `PYTHONPYCACHEPREFIX`, so a run never touches `data/`, the live transcripts,
or the events DB. A test may also set its own `tempfile.mkdtemp()`.

## Writing a test

- `REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))`
  (three levels up from `tests/acceptance/`).
- `sys.path.insert(0, os.path.join(REPO, "src"))` then import `longrun`.
- Define `check(name, ok, detail="")`, print `PASS`/`FAIL`, `sys.exit(1)` on any failure.
- Name it `vNNN_topic.py` (NNN = the JAG issue number). Drop it in `acceptance/`.
- Keep it deterministic: no sleep-loops, no live model, no wall-clock races.

## Current count

Run `bash tests/battery.sh` and read the last line (`=== battery: N/N GREEN ===`).
As of the JAG-391 pass: **125/125**.
