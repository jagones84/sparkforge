#!/bin/bash
ADB="/usr/bin/adb -s oneplus-15r:5555"
SC="/home/jagones/Repositories/sparkforge/trash/scan_ui.py"
$ADB shell input tap 633 268
sleep 2
$ADB shell input tap 507 2324
sleep 1
$ADB shell input text "esegui%spwd"
sleep 1
$ADB shell uiautomator dump /sdcard/f.xml >/dev/null 2>&1
$ADB pull /sdcard/f.xml /home/jagones/f.xml >/dev/null 2>&1
echo "=== bottom nodes ==="
python3 "$SC" /home/jagones/f.xml | tail -n 12
