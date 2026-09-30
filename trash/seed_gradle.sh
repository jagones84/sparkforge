#!/bin/bash
set -e
SRC=/home/jagones/Repositories/android-dev/projects/HelloDGX
DST=/home/jagones/Repositories/tododemo
mkdir -p "$DST/gradle/wrapper"
cp "$SRC/gradlew" "$DST/gradlew"
cp "$SRC/gradlew.bat" "$DST/gradlew.bat" 2>/dev/null || true
cp "$SRC/gradle/wrapper/gradle-wrapper.jar" "$DST/gradle/wrapper/gradle-wrapper.jar"
cp "$SRC/gradle/wrapper/gradle-wrapper.properties" "$DST/gradle/wrapper/gradle-wrapper.properties"
chmod +x "$DST/gradlew"
printf 'sdk.dir=/home/jagones/Repositories/android-dev/android-sdk\n' > "$DST/local.properties"
printf 'org.gradle.jvmargs=-Xmx2048m\nandroid.useAndroidX=true\n' > "$DST/gradle.properties"
echo "--- tododemo tree ---"
find "$DST" -maxdepth 3 -type f | sort
