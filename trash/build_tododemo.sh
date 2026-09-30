#!/bin/bash
cd /home/jagones/Repositories/tododemo
export ANDROID_HOME=/home/jagones/Repositories/android-dev/android-sdk
export ANDROID_SDK_ROOT=/home/jagones/Repositories/android-dev/android-sdk
export JAVA_HOME=/usr/lib/jvm/java-17-openjdk-arm64
./gradlew :app:assembleDebug --no-daemon 2>&1 | tail -n 40
echo "GRADLE_EXIT=${PIPESTATUS[0]}"
echo "--- apk ---"
find /home/jagones/Repositories/tododemo -name '*.apk' -print
