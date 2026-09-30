#!/bin/bash
set -e
cd /home/jagones/Repositories/sparkforge
git add api_v02.py config/tools.yaml config/routing.yaml
git commit -m "JAG-61: agent loop carries turn history across iterations

- api_v02.agent_run_v2 rebuilt the message list from scratch every step, so
  the model never saw its own tool observations and looped forever (the
  symptom read as 'the model cannot install the app'). A persistent hist now
  feeds the assistant action + its observation back into the next iteration.
- config/tools.yaml: add /home/jagones/Repositories as an allowed root for
  fs.read/write/edit and git ('.' resolves to REPO=sparkforge, which blocked
  writing to sibling repos such as tododemo).
- config/routing.yaml: route chat+agent to qwen-3.8-27b-uncensored-q8."
git log --oneline -n 3
