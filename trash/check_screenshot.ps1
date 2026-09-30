$f = "z:\Repositories\sparkforge\trash\sparkpulse_running.png"
$b = [IO.File]::ReadAllBytes($f)
Write-Host "Length: $($b.Length)"
Write-Host "First 16 bytes: $((($b[0..15] | ForEach-Object { '{0:X2}' -f $_ }) -join ' '))"
Write-Host "Last 16 bytes: $((($b[(-16..-1)] | ForEach-Object { '{0:X2}' -f $_ }) -join ' '))"
$pulled = "z:\Repositories\sparkforge\trash\sparkpulse_running_pull.png"
$bp = [IO.File]::ReadAllBytes($pulled)
Write-Host ""
Write-Host "Pulled Length: $($bp.Length)"
Write-Host "Pulled First 8 bytes: $((($bp[0..7] | ForEach-Object { '{0:X2}' -f $_ }) -join ' '))"
Write-Host "Pulled Last 8 bytes: $((($bp[(-8..-1)] | ForEach-Object { '{0:X2}' -f $_ }) -join ' '))"
