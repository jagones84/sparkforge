---
name: Bug report
about: Something is broken in Longrun
title: "[bug] "
labels: bug
assignees: ""
---

<!-- Please keep it factual: what you ran, what you saw, what you expected. -->

## What happened

<!-- The actual behaviour. Paste the exact error / output. -->

## What you expected

## Steps to reproduce

1.
2.
3.

## Environment

- Longrun version / commit:
- OS: <!-- e.g. Ubuntu 24.04 (DGX Spark) / Windows 11 -->
- Python: <!-- `python3 --version` -->
- Model / provider: <!-- e.g. dgx:qwen-3.8-27b / openrouter:... -->
- Sandbox: <!-- docker / bwrap / nsjail / none -->

## Does the battery pass on your checkout?

```bash
bash tests/battery.sh
```

<!-- Paste the last line, e.g. `=== battery: 125/125 GREEN ===` or the failing test. -->

## Anything else

<!-- Logs (`journalctl --user -u longrun.service -f`), feed events, screenshots. -->
