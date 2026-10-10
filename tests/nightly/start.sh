#!/usr/bin/env bash
set -u
ROOT=/home/jagones/Repositories/longrun
cd $ROOT
rm -f .nightly_stop
chmod +x scripts/nightly_mega.sh
nohup bash scripts/nightly_mega.sh > outputs/nohup_nightly.log 2>&1 &
echo $!
