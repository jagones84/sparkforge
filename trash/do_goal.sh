#!/bin/bash
ADB="/usr/bin/adb -s oneplus-15r:5555"
SC="/home/jagones/Repositories/sparkforge/trash/scan_ui.py"
$ADB shell monkey -p com.jagones.sparkpulse -c android.intent.category.LAUNCHER 1 >/dev/null 2>&1
sleep 3
$ADB shell input tap 633 268
sleep 2
$ADB shell input tap 507 2324
sleep 1
$ADB shell input text "esegui%spwd"
sleep 1
$ADB shell uiautomator dump /sdcard/ui4.xml >/dev/null 2>&1
$ADB pull /sdcard/ui4.xml /home/jagones/ui4.xml >/dev/null 2>&1
echo "--- bottom nodes ---"
python3 "$SC" /home/jagones/ui4.xml | tail -n 16
