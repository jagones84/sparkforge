#!/bin/bash
# Run SparkPulse JVM unit tests (DGX, JDK 17)
set -e
cd /home/jagones/Repositories/sparkpulse-app

export JAVA_HOME=/usr/lib/jvm/java-17-openjdk-arm64
export ANDROID_HOME=/home/jagones/Repositories/android-dev/android-sdk
export PATH="$JAVA_HOME/bin:$ANDROID_HOME/platform-tools:$PATH"

echo "--- START unit tests ---"
./gradlew --no-daemon testDebugUnitTest 2>&1 | tail -80
echo "--- DONE ---"
