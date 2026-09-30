# install sparkpulse-app on OnePlus 15R via Tailscale ADB
$ErrorActionPreference = "Stop"
$adb = "$env:LOCALAPPDATA\Android\Sdk\platform-tools\adb.exe"
$dev = "oneplus-15r:5555"
$apk = "z:\Repositories\sparkpulse-app\app\build\outputs\apk\debug\app-debug.apk"

Write-Host "=== device check ==="
& $adb -s $dev shell getprop ro.product.model

Write-Host "=== APK info ==="
Get-Item $apk | Select-Object FullName, Length, LastWriteTime | Format-List

Write-Host "=== package version (current) ==="
& $adb -s $dev shell dumpsys package com.jagones.sparkpulse | Select-String -Pattern "versionName|versionCode|firstInstall|lastUpdate" | Select-Object -First 6

Write-Host "=== uninstall (will skip if not present) ==="
# NO, do not uninstall — we want to update via -r. Skip uninstall.

Write-Host "=== install -r ==="
& $adb -s $dev install -r $apk 2>&1
Write-Host "ExitCode=$LASTEXITCODE"

Write-Host "=== package version (after) ==="
& $adb -s $dev shell dumpsys package com.jagones.sparkpulse | Select-String -Pattern "versionName|versionCode|firstInstall|lastUpdate" | Select-Object -First 6

Write-Host "=== launch ==="
& $adb -s $dev shell monkey -p com.jagones.sparkpulse -c android.intent.category.LAUNCHER 1 2>&1 | Select-String -Pattern "Events injected|No activities"

Write-Host "=== current focus ==="
Start-Sleep -Seconds 3
& $adb -s $dev shell dumpsys window | Select-String -Pattern "mCurrentFocus|mFocusedApp" | Select-Object -First 4

Write-Host "=== screenshot ==="
$screenshot = "z:\Repositories\sparkforge\trash\sparkpulse_installed.png"
& $adb -s $dev exec-out screencap -p > $screenshot
Write-Host "Saved: $screenshot ($(Get-Item $screenshot).Length bytes)"
