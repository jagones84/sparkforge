#!/bin/bash
cd /home/jagones/Repositories/sparkpulse-app
export ANDROID_HOME=/home/jagones/Repositories/android-dev/android-sdk
export ANDROID_SDK_ROOT="$ANDROID_HOME"
export JAVA_HOME=/usr/lib/jvm/java-17-openjdk-arm64
./gradlew testDebugUnitTest assembleDebug 2>&1 | tail -n 8
echo "GRADLE_EXIT=${PIPESTATUS[0]}"
/usr/bin/adb connect oneplus-15r:5555
/usr/bin/adb -s oneplus-15r:5555 install -r \
  /home/jagones/Repositories/sparkpulse-app/app/build/outputs/apk/debug/app-debug.apk
echo "INSTALL_EXIT=$?"
/usr/bin/adb -s oneplus-15r:5555 shell dumpsys package com.jagones.sparkpulse | grep -E 'versionName|versionCode|lastUpdateTime'
