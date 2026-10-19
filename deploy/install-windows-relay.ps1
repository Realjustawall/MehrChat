# Run as Administrator. The prebuilt executable includes its Python runtime.
$ErrorActionPreference='Stop'
$root=Split-Path $PSScriptRoot -Parent
$target=Join-Path $env:ProgramFiles 'MehrChatRelay'
$data=Join-Path $env:ProgramData 'MehrRelay'
New-Item -ItemType Directory -Force -Path $target,$data | Out-Null
Copy-Item (Join-Path $root 'dist\MehrRelay.exe') $target -Force
& icacls $data /inheritance:r /grant:r '*S-1-5-18:(OI)(CI)F' '*S-1-5-32-544:(OI)(CI)F' | Out-Null
$action=New-ScheduledTaskAction -Execute (Join-Path $target 'MehrRelay.exe') -Argument ('--data "'+$data+'" --port 8787') -WorkingDirectory $target
$trigger=New-ScheduledTaskTrigger -AtStartup
$settings=New-ScheduledTaskSettingsSet -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero)
Register-ScheduledTask -TaskName 'MehrChatRelay' -Action $action -Trigger $trigger -Settings $settings -User SYSTEM -RunLevel Highest -Force | Out-Null
if(!(Get-NetFirewallRule -DisplayName 'MehrChat Relay TCP' -ErrorAction SilentlyContinue)){New-NetFirewallRule -DisplayName 'MehrChat Relay TCP' -Direction Inbound -Protocol TCP -LocalPort 8787 -Action Allow | Out-Null}
Start-ScheduledTask -TaskName 'MehrChatRelay'
Write-Host ('Connection pin: '+(Join-Path $data 'relay-public.json'))
Write-Host ('Admin token: '+(Join-Path $data 'admin-token.txt'))
Write-Host 'Admin panel: http://127.0.0.1:8788'
