#!/bin/bash
# JAG-61: background auto-approver — drains pending approvals every 5s for ~35 min.
for i in $(seq 1 420); do
  python3 /home/jagones/Repositories/sparkforge/trash/approve_all.py
  sleep 5
done
