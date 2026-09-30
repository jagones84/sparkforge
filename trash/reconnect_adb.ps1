$adb = "$env:LOCALAPPDATA\Android\Sdk\platform-tools\adb.exe"
$dev = "oneplus-15r:5555"
& $adb disconnect 2>&1 | Out-Null
for ($i = 0; $i -lt 8; $i++) {
    & $adb connect $dev 2>&1 | Out-Null
    Start-Sleep -Seconds 2
    $st = (& $adb devices | Select-String -Pattern $dev)
    if ($st -match "device$") { Write-Host "connected at try $i"; break }
}
& $adb devices -l
& $adb -s $dev shell echo PING 2>&1
