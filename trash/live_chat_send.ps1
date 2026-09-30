# Live proof 2: type a tool-triggering chat message and screenshot the result
$adb = "$env:LOCALAPPDATA\Android\Sdk\platform-tools\adb.exe"
$dev = "oneplus-15r:5555"
$out = "z:\Repositories\sparkforge\trash"

Write-Host "=== tap chat field ==="
& $adb -s $dev shell input tap 472 2597
Start-Sleep -Seconds 1

Write-Host "=== type message ==="
& $adb -s $dev shell "input text 'usa il tool skills action=list e dimmi quante skill ci sono'"
Start-Sleep -Seconds 2

Write-Host "=== tap SEND ==="
& $adb -s $dev shell input tap 1073 2597
Write-Host "sent; waiting for tool + reply..."
Start-Sleep -Seconds 18

Write-Host "=== screenshot ==="
& $adb -s $dev shell screencap -p /sdcard/sparkpulse_toolcard.png
& $adb -s $dev pull /sdcard/sparkpulse_toolcard.png "$out\sparkpulse_toolcard.png" 2>&1 | Out-Null
Get-Item "$out\sparkpulse_toolcard.png" | Select-Object Length | Format-List

Write-Host "=== focus check ==="
& $adb -s $dev shell dumpsys window | Select-String -Pattern "mCurrentFocus" | Select-Object -First 1
