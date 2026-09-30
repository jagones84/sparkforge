#!/bin/bash
# Ask the status server to preload a model on the llama.cpp router (fire-and-forget).
MODEL="${1:-qwen-3.8-27b-uncensored-q8}"
curl -s -m 10 -X POST http://100.102.61.23:8787/api/commands \
  -H "Content-Type: application/json" \
  -d "{\"action\":\"switch_model\",\"model\":\"$MODEL\"}"
echo
echo "requested load of $MODEL"
