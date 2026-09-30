#!/bin/bash
echo "===== sparkforge status ====="
cd /home/jagones/Repositories/sparkforge
git status --short | head -n 30
echo "--- tracked .env check (must be empty) ---"
git ls-files | grep -i "\.env" | grep -v "\.env\.template" || echo "no .env tracked: OK"
git add -A
git commit -q -m "JAG-71/72: provider+model catalogue, mobile model picker, ctx x/max fix, memory embedder cache

- providers.yaml/providers.py: dgx+win llama.cpp, vLLM, OpenRouter (GLM/DeepSeek
  flash), DeepSeek original; keys via env refs only, .gitignore hides .env
- /api/providers + provider-aware routing (_chat_endpoint) and GET /api/context?model=
- context x now mirrors the real prompt (shared _system_prompt + same budget +
  memory retrieval); max is model-aware: remote windows from live OpenRouter
  metadata (no hardcoded guess), warmed off the request path at startup
- memory: cache the sentence-transformer embedder and disable a dead embeddings
  endpoint after one probe (was reloading / 30s-timeout per kind per search)
- tests: v075 12/12, v074 6/6; app v1.6.17 model picker" && echo COMMIT_OK
git log -n 1 --oneline
echo
echo "===== sparkpulse-app ====="
cd /home/jagones/Repositories/sparkpulse-app
git status --short | head -n 30
git add -A
git commit -q -m "v1.6.17 (JAG-71): in-app LLM picker (local / DeepSeek / OpenRouter)

- ForgeModelPicker panel + toolbar chip + rail entry driven by GET /api/providers
- selected <provider>:<model> ref persisted and sent with chat/agent/context" && echo COMMIT_OK
git log -n 1 --oneline
