#!/bin/bash
# JAG-61: end-to-end headless goal — build+install an APK from the DGX.
TOKEN=REDACTED-COMPROMISED-TOKEN
GOAL='Crea una semplice app Android ToDo in /home/jagones/Repositories/tododemo (progetto Gradle minimale con gradlew). Poi compila la APK con gradlew assembleDebug e installala sul OnePlus 15R con adb install -r. ANDROID_HOME e JAVA_HOME sono gia impostati. Vai fino ad avere la app installata sul telefono; non fermarti a spiegare.'
ENC=$(python3 -c "import urllib.parse,sys;print(urllib.parse.quote(sys.argv[1]))" "$GOAL")
rm -f /tmp/e2e.out
nohup curl -N -s -H "Authorization: Bearer $TOKEN" \
  "http://127.0.0.1:8790/api/agent/run?goal=$ENC&max_steps=40" > /tmp/e2e.out 2>&1 &
echo "started pid $!"
sleep 2
echo "--- head ---"
head -c 300 /tmp/e2e.out
