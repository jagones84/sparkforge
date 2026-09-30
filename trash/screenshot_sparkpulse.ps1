# § 8.4 wakeup sequence + screenshot
$adb = "$env:LOCALAPPDATA\Android\Sdk\platform-tools\adb.exe"
$dev = "oneplus-15r:5555"
$png = "z:\Repositories\sparkforge\trash\sparkpulse_running.png"

Write-Host "=== 1. WAKEUP ==="
& $adb -s $dev shell input keyevent 224
& $adb -s $dev shell svc power stayon true

Write-Host "=== 2. HOME ==="
& $adb -s $dev shell input keyevent 3
Start-Sleep -Seconds 2

Write-Host "=== 3. launch app ==="
& $adb -s $dev shell am start -n com.jagones.sparkpulse/.MainActivity
Start-Sleep -Seconds 4

Write-Host "=== 4. focus ==="
& $adb -s $dev shell dumpsys window | Select-String -Pattern "mCurrentFocus" | Select-Object -First 1

Write-Host "=== 5. screenshot ==="
& $adb -s $dev exec-out screencap -p > $png
Get-Item $png | Select-Object Length, LastWriteTime | Format-List

Write-Host "=== 6. pull also to /sdcard + base64 dump ==="
& $adb -s $dev shell screencap -p /sdcard/sparkpulse_running.png
& $adb -s $dev pull /sdcard/sparkpulse_running.png z:\Repositories\sparkforge\trash\sparkpulse_running_pull.png | Out-Null
Get-Item z:\Repositories\sparkforge\trash\sparkpulse_running_pull.png | Select-Object Length | Format-List
