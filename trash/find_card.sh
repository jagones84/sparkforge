#!/bin/bash
ADB="/usr/bin/adb -s oneplus-15r:5555"
for i in 1 2 3 4 5; do
  $ADB shell input swipe 636 1500 636 1000 300
  sleep 1
done
sleep 1
$ADB exec-out screencap -p > /home/jagones/shot_cards.png
ls -la /home/jagones/shot_cards.png
