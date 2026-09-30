$adb = "$env:LOCALAPPDATA\Android\Sdk\platform-tools\adb.exe"
Start-Sleep -Seconds 20
& $adb -s oneplus-15r:5555 shell screencap -p /sdcard/sp2.png
& $adb -s oneplus-15r:5555 pull /sdcard/sp2.png z:\Repositories\sparkforge\trash\sp2.png | Out-Null
Get-Item z:\Repositories\sparkforge\trash\sp2.png | Select-Object Length
