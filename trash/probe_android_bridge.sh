#!/bin/bash
# Probe 1 — find Android/mobile bridge sources
echo "=== A. Android source inside sparkforge? ==="
find /home/jagones/Repositories/sparkforge -maxdepth 3 -type f \
  \( -name "*.kt" -o -name "*.java" -o -name "build.gradle*" \
     -o -name "AndroidManifest.xml" -o -name "settings.gradle*" \) 2>/dev/null | head -20

echo
echo "=== B. sparkpulse folder anywhere on DGX (jagones home) ==="
find /home/jagones -maxdepth 5 -type d \( -iname "*sparkpulse*" -o -iname "*spark-pulse*" \) 2>/dev/null | head -10

echo
echo "=== C. sparkpulse backup location ==="
ls -la /home/jagones/Backups/ 2>/dev/null | grep -i pulse

echo
echo "=== D. skills/android/ entries (skill definitions) ==="
ls /home/jagones/Repositories/sparkforge/skills/android/ 2>&1

echo
echo "=== E. Any android/mobile/app/pulse file at sparkforge top-level ==="
ls /home/jagones/Repositories/sparkforge/ | grep -iE "android|mobile|app|pulse" || echo "NONE"

echo
echo "=== F. /home/jagones top-level repos (look for pulse / app) ==="
ls /home/jagones/Repositories/ | grep -iE "pulse|mobile|sparkpulse|spark-pulse" || echo "NONE in /home/jagones/Repositories"
