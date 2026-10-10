#!/usr/bin/env bash
# Nightly mega debug loop - runs until STOP file or 8h.
# Logs to outputs/<date>_nightly/. Safe autofix only with battery gate.
set -u
ROOT=/home/jagones/Repositories/longrun
cd $ROOT
STAMP=$(date +%Y%m%d_%H%M_nightly)
OUT=$ROOT/outputs/$STAMP
mkdir -p $OUT
LOG=$OUT/nightly.log
STOP=$ROOT/.nightly_stop
END=$(( $(date +%s) + 28800 ))

log() {
  echo "[Level: INFO] | [$(date -u +%FT%TZ)] | [nightly] | $1" >> $LOG
}

log "start pid $$ out $OUT"
if [ ! -d .venv ]; then
  python3 -m venv .venv >> $LOG 2>&1
fi
.venv/bin/pip install -q ruff mypy bandit mutmut hypothesis pytest >> $LOG 2>&1

ITER=0
while true; do
  if [ -f $STOP ]; then
    log "stop file found, exit"
    break
  fi
  NOW=$(date +%s)
  if [ $NOW -ge $END ]; then
    log "8h budget reached, exit"
    break
  fi
  ITER=$((ITER+1))
  log "=== iter $ITER ==="

  .venv/bin/ruff check src/longrun > $OUT/ruff_i$ITER.txt 2>&1
  echo "ruff_exit=$? iter=$ITER" >> $LOG

  .venv/bin/mypy src/longrun --ignore-missing-imports > $OUT/mypy_i$ITER.txt 2>&1
  echo "mypy_exit=$? iter=$ITER" >> $LOG

  .venv/bin/bandit -r src/longrun -ll -q > $OUT/bandit_i$ITER.txt 2>&1
  echo "bandit_exit=$? iter=$ITER" >> $LOG

  bash tests/battery.sh > $OUT/battery_i$ITER.txt 2>&1
  B=$?
  echo "battery_exit=$B iter=$ITER" >> $LOG
  tail -n 2 $OUT/battery_i$ITER.txt >> $LOG

  .venv/bin/pytest tests/properties/ -q > $OUT/props_i$ITER.txt 2>&1
  echo "props_exit=$? iter=$ITER" >> $LOG

  if [ $B -ne 0 ]; then
    log "battery red, skip autofix this iter"
    sleep 60
    continue
  fi

  cp -a src/longrun $OUT/src_backup_i$ITER
  .venv/bin/ruff check src/longrun --fix > $OUT/ruff_fix_i$ITER.txt 2>&1
  bash tests/battery.sh > $OUT/battery_postfix_i$ITER.txt 2>&1
  B2=$?
  echo "battery_postfix_exit=$B2 iter=$ITER" >> $LOG
  if [ $B2 -ne 0 ]; then
    log "autofix broke battery, revert iter $ITER"
    rm -rf src/longrun
    cp -a $OUT/src_backup_i$ITER src/longrun
  else
    log "autofix kept green iter $ITER"
  fi
  sleep 60
done
log "done iters $ITER"
