#!/bin/bash
cd /home/jagones/Repositories/sparkpulse-app
export ANDROID_HOME=/home/jagones/Repositories/android-dev/android-sdk
export ANDROID_SDK_ROOT="$ANDROID_HOME"
export JAVA_HOME=/usr/lib/jvm/java-17-openjdk-arm64
./gradlew testDebugUnitTest assembleDebug 2>&1 | tail -n 60
echo "EXIT=${PIPESTATUS[0]}"
echo "--- apk ---"
find /home/jagones/Repositories/sparkpulse-app/app/build/outputs/apk -name '*.apk' -print 2>/dev/null
