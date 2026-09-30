#!/bin/bash
ADB="/usr/bin/adb -s oneplus-15r:5555"
SC="/home/jagones/Repositories/sparkforge/trash/scan_ui.py"
$ADB shell settings put system accelerometer_rotation 0
$ADB shell settings put system user_rotation 0
sleep 1
$ADB shell monkey -p com.jagones.sparkpulse -c android.intent.category.LAUNCHER 1 >/dev/null 2>&1
sleep 3
$ADB shell uiautomator dump /sdcard/d.xml >/dev/null 2>&1
$ADB pull /sdcard/d.xml /home/jagones/d.xml >/dev/null 2>&1
echo "=== FORGE tab + fields ==="
python3 "$SC" /home/jagones/d.xml | grep -E "FORGE|EditText|SEND|Obiettivo"
