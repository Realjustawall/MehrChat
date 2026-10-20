# Run as Administrator. The prebuilt executable includes its Python runtime.
$ErrorActionPreference='Stop'
$root=Split-Path $PSScriptRoot -Parent
$target=Join-Path $env:ProgramFiles 'MehrChatRelay'
$data=Join-Path $env:ProgramData 'MehrRelay'
New-Item -ItemType Directory -Force -Path $target,$data | Out-Null
$installedExecutable=Join-Path $target 'MehrRelay.exe'
if(Get-ScheduledTask -TaskName 'MehrChatRelay' -ErrorAction SilentlyContinue){
    Stop-ScheduledTask -TaskName 'MehrChatRelay'
    # PyInstaller onefile has a child process which can outlive the task host.
    # Match both our exact installed path and data argument; never stop by name alone.
    $escapedData=[regex]::Escape($data)
    $dataPattern='(?:^|\s)--data\s+(?:"'+$escapedData+'"|'+$escapedData+')(?=\s|$)'
    Get-CimInstance Win32_Process -Filter "Name='MehrRelay.exe'" | Where-Object {
        $_.ExecutablePath -ieq $installedExecutable -and $_.CommandLine -match $dataPattern
    } | ForEach-Object {
        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
    }
}
for($attempt=0;$attempt -lt 40;$attempt++){
    try{Copy-Item (Join-Path $root 'dist\MehrRelay.exe') $target -Force;break}
    catch{if($attempt -eq 39){throw};Start-Sleep -Milliseconds 250}
}
& icacls $target /grant:r '*S-1-5-19:(OI)(CI)RX' | Out-Null
if($LASTEXITCODE -ne 0){throw 'Could not grant Local Service access to the executable'}
& icacls $data /inheritance:r /grant:r '*S-1-5-18:(OI)(CI)F' '*S-1-5-32-544:(OI)(CI)F' '*S-1-5-19:(OI)(CI)M' | Out-Null
if($LASTEXITCODE -ne 0){throw 'Could not protect relay data permissions'}
$action=New-ScheduledTaskAction -Execute $installedExecutable -Argument ('--data "'+$data+'" --port 8787') -WorkingDirectory $target
$trigger=New-ScheduledTaskTrigger -AtStartup
$settings=New-ScheduledTaskSettingsSet -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero)
$principal=New-ScheduledTaskPrincipal -UserId 'S-1-5-19' -LogonType ServiceAccount -RunLevel Limited
Register-ScheduledTask -TaskName 'MehrChatRelay' -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Force | Out-Null
if(!(Get-NetFirewallRule -DisplayName 'MehrChat Relay TCP' -ErrorAction SilentlyContinue)){New-NetFirewallRule -DisplayName 'MehrChat Relay TCP' -Direction Inbound -Protocol TCP -LocalPort 8787 -Action Allow | Out-Null}
Start-ScheduledTask -TaskName 'MehrChatRelay'
Write-Host ('Connection pin: '+(Join-Path $data 'relay-public.json'))
Write-Host ('Admin token: '+(Join-Path $data 'admin-token.txt'))
Write-Host 'Admin panel: http://127.0.0.1:8788'
