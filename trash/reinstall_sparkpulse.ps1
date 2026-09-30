$adb = "$env:LOCALAPPDATA\Android\Sdk\platform-tools\adb.exe"
$dev = "oneplus-15r:5555"
$apk = "z:\Repositories\sparkpulse-app\app\build\outputs\apk\debug\app-debug.apk"

Write-Host "=== re-connect ==="
& $adb connect $dev 2>&1

Write-Host "=== install -r ==="
& $adb -s $dev install -r $apk 2>&1

Write-Host "=== installed version ==="
& $adb -s $dev shell dumpsys package com.jagones.sparkpulse | Select-String -Pattern "versionName|versionCode|lastUpdateTime" | Select-Object -First 4

Write-Host "=== launch ==="
& $adb -s $dev shell input keyevent 224
& $adb -s $dev shell wm dismiss-keyguard
& $adb -s $dev shell am start -n com.jagones.sparkpulse/.MainActivity
Start-Sleep -Seconds 4
& $adb -s $dev shell dumpsys window | Select-String -Pattern "mCurrentFocus" | Select-Object -First 1
