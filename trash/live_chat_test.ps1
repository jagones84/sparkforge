# Live proof: launch SparkPulse, send a chat msg that triggers a tool, screenshot
$adb = "$env:LOCALAPPDATA\Android\Sdk\platform-tools\adb.exe"
$dev = "oneplus-15r:5555"
$out = "z:\Repositories\sparkforge\trash"

Write-Host "=== size ==="
& $adb -s $dev shell wm size

Write-Host "=== wake + dismiss keyguard ==="
& $adb -s $dev shell input keyevent 224
& $adb -s $dev shell wm dismiss-keyguard
Start-Sleep -Seconds 2

Write-Host "=== launch app ==="
& $adb -s $dev shell am start -n com.jagones.sparkpulse/.MainActivity
Start-Sleep -Seconds 5

Write-Host "=== focus ==="
& $adb -s $dev shell dumpsys window | Select-String -Pattern "mCurrentFocus" | Select-Object -First 1

Write-Host "=== uiautomator dump ==="
& $adb -s $dev shell uiautomator dump /sdcard/ui.xml 2>&1
& $adb -s $dev pull /sdcard/ui.xml "$out\ui.xml" 2>&1 | Out-Null
$xml = Get-Content "$out\ui.xml" -Raw
# print nodes that look like text fields / buttons
[regex]::Matches($xml, '<node[^>]*>') | ForEach-Object {
    $n = $_.Value
    if ($n -match 'EditText|Button' -or $n -match 'Messaggio|SEND|Obiettivo') {
        $t = if ($n -match 'text="([^"]*)"') { $Matches[1] } else { "" }
        $c = if ($n -match 'class="([^"]*)"') { $Matches[1] } else { "" }
        $b = if ($n -match 'bounds="([^"]*)"') { $Matches[1] } else { "" }
        if ($t -or $c -match 'EditText|Button') { Write-Host "$c | '$t' | $b" }
    }
}
