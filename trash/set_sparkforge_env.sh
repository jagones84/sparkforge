#!/bin/bash
# JAG-59: point the SparkForge service at the real Android SDK + JDK 17 so the
# on-DGX shell (agent) can build/install APKs. Idempotent.
set -e
ENV=/home/jagones/.config/sparkforge/env
if grep -q ANDROID_HOME "$ENV"; then
  echo "ANDROID_HOME already present — not touching"
else
  cp -a "$ENV" "$ENV.bak-jag59-$(date +%Y%m%d-%H%M%S)"
  cat >> "$ENV" <<'EOF'
# JAG-59: Android/Java toolchain for the on-DGX shell (the agent builds APKs here)
JAVA_HOME=/usr/lib/jvm/java-17-openjdk-arm64
ANDROID_HOME=/home/jagones/Repositories/android-dev/android-sdk
ANDROID_SDK_ROOT=/home/jagones/Repositories/android-dev/android-sdk
PATH=/usr/lib/jvm/java-17-openjdk-arm64/bin:/home/jagones/Repositories/android-dev/android-sdk/platform-tools:/home/jagones/Repositories/android-dev/android-sdk/cmdline-tools/latest/bin:/home/jagones/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
EOF
  echo "appended toolchain env"
fi
systemctl --user daemon-reload
systemctl --user restart sparkforge.service
echo "sparkforge restarted"
