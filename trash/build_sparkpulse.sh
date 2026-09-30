#!/bin/bash
# build sparkpulse-app via gradlew assembleDebug (DGX, JDK 17)
set -e
cd /home/jagones/Repositories/sparkpulse-app

export JAVA_HOME=/usr/lib/jvm/java-17-openjdk-arm64
export ANDROID_HOME=/home/jagones/Repositories/android-dev/android-sdk
export PATH="$JAVA_HOME/bin:$ANDROID_HOME/cmdline-tools/latest/bin:$ANDROID_HOME/platform-tools:$PATH"

# Sanity
java -version
echo "ANDROID_HOME=$ANDROID_HOME"
ls "$ANDROID_HOME/build-tools/" 2>/dev/null | head
echo "--- START build ---"
./gradlew --no-daemon assembleDebug 2>&1 | tail -120
echo "--- DONE ---"
find app/build/outputs/apk -name "*.apk" -exec ls -lh {} \; 2>&1
