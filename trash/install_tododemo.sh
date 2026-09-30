#!/bin/bash
ADB=/usr/bin/adb
APK=/home/jagones/Repositories/tododemo/app/build/outputs/apk/debug/app-debug.apk
DEV=oneplus-15r:5555
echo "--- devices ---"
$ADB devices
echo "--- connect ---"
$ADB connect "$DEV" || true
echo "--- install ---"
$ADB -s "$DEV" install -r "$APK"
echo "INSTALL_EXIT=$?"
echo "--- verify ---"
$ADB -s "$DEV" shell pm list packages | grep -i todo || true
