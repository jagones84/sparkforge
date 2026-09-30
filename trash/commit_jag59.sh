#!/bin/bash
# JAG-59: shell runs on the DGX host so the agent can use the real toolchain
set -e

cd /home/jagones/Repositories/sparkforge
git add config/tools.yaml sandbox.py
git commit -m "feat(sandbox): run shell on the DGX host (backend: none)

Everything must live on the DGX: the alpine container had no
JDK/Gradle/Android SDK/adb and could not see the repo, so the agent could
not build or install APKs. Run shell on the host instead, raise the
per-command timeout to 900s (builds) and widen fs.write/fs.edit roots to
the repo. Mutating commands stay approval-gated and deny-listed."
echo "--- sparkforge ---"
git log -1 --oneline
echo "DONE"
