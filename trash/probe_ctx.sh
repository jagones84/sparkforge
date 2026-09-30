#!/bin/bash
echo "== /v1/models =="
curl -s http://127.0.0.1:8080/v1/models
echo
echo "== /props =="
curl -s http://127.0.0.1:8080/props
echo
echo "== /v1/models?meta =="
curl -s http://127.0.0.1:8080/models
echo
