# SparkForge Plan

*Living document — mirrors the in-app PLAN store (`GET /api/plan`). Updated 2026-09-28.*

## Goal
A state-of-the-art, mobile-commandable agent harness on the DGX Spark: local LLM (router :8080) inside a frontier-style harness with visible reasoning, planning, task execution, a live loopback feed, WebUI and CLI.

## Done — v0.1 "Genesis" (2026-09-28)

- ✅ Frontier-harness research survey with 2026 citations (docs/RESEARCH-frontier-harnesses-2026.md)
- ✅ Harness server: chat (one-shot + SSE stream) with visible CoT (`reasoning_content` + `thinthink`)
- ✅ Planner module: goal → JSON strategy steps (model-generated, robust extraction)
- ✅ TASKS board: status machine `todo → doing → done` + remaining bullets
- ✅ Agent loop: `thought → action → observation`, structurally sandboxed to harness stores
- ✅ Loopback feed: SSE `/api/feed`, monotonic ids, backlog replay (`?since=`)
- ✅ Frontier WebUI: dark glass UI, thinking timeline, plan/tasks panels, live feed rail
- ✅ CLI `forge.py`: chat/agent/plan/tasks/status/models/feed
- ✅ Mobile API: `--host 0.0.0.0` for Tailscale exposure, optional bearer token
- ✅ SparkPulse preserved & backed up: `/home/jagones/Backups/sparkpulse-backup-20260928-231607.tar.gz` (38 MB, 1501 files)

## Remaining

- [ ] **v0.2 — Real tools with approval gates**: shell/file tools behind an explicit allowlist + per-action approval queue (Codex/Cline pattern); tool results as observations
- [ ] **v0.2 — SparkPulse bridge**: "Command" tab in the SparkPulse Android app hitting `/api/chat/stream` + `/api/feed`; `POST /api/commands` adapter in sparkpulse-server
- [ ] **v0.2 — WebUI auth flow** for `--token` mode (server enforces today; UI needs a token prompt)
- [ ] **v0.3 — MCP client**: connect 70+ existing MCP tools (Goose pattern)
- [ ] **v0.3 — Subagent delegation** (deepagents pattern): spawn child agent runs from the loop
- [ ] **v0.3 — Persistent memory store** with write rules (markdown + optional vector index)
- [ ] **v0.3 — Speech I/O**: whisper.cpp STT + sherpa-onnx TTS for voice commands from mobile
- [ ] **v0.4 — Eval harness**: gold task set + scoring for loop quality (Winder.AI pattern)
- [ ] **v0.4 — systemd unit** for always-on service (loopback feed alive for the phone 24/7)

## Remaining bullets (machine-readable)

`GET /api/tasks` exposes the same list as the tasks board; this file is the human mirror.
