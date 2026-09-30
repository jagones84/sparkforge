$adb = "$env:LOCALAPPDATA\Android\Sdk\platform-tools\adb.exe"
$dev = "oneplus-15r:5555"
& $adb -s $dev shell input keyevent 224 | Out-Null
& $adb -s $dev shell wm dismiss-keyguard | Out-Null
& $adb -s $dev shell am start -n com.jagones.sparkpulse/.MainActivity | Out-Null
Start-Sleep -Seconds 4
& $adb -s $dev shell uiautomator dump /sdcard/ui2.xml 2>&1 | Out-Null
& $adb -s $dev pull /sdcard/ui2.xml z:\Repositories\sparkforge\trash\ui2.xml 2>&1 | Out-Null
$xml = Get-Content z:\Repositories\sparkforge\trash\ui2.xml -Raw
[regex]::Matches($xml, '<node[^>]*>') | ForEach-Object {
    $n = $_.Value
    $c = if ($n -match 'class="([^"]*)"') { $Matches[1] } else { "" }
    $t = if ($n -match 'text="([^"]*)"') { $Matches[1] } else { "" }
    $b = if ($n -match 'bounds="([^"]*)"') { $Matches[1] } else { "" }
    if ($c -match 'EditText|Button' -or $t -match 'Obiettivo|Messaggio|SEND|APPROVA|NEGA|AGENTE') {
        Write-Host "$c | '$t' | $b"
    }
}
Write-Host "=== raw length: $($xml.Length) ==="
