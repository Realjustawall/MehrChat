# Run as Administrator after reviewing the paths. Installs a persistent startup task.
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$python = Join-Path $root '.venv\Scripts\python.exe'
if (!(Test-Path $python)) { throw 'Run start-windows-server.ps1 once first' }
$arguments = '-m mehrchat.server --data "' + (Join-Path $env:ProgramData 'MehrRelay') + '" --port 8787'
$action = New-ScheduledTaskAction -Execute $python -Argument $arguments -WorkingDirectory $root
$trigger = New-ScheduledTaskTrigger -AtStartup
$settings = New-ScheduledTaskSettingsSet -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero)
Register-ScheduledTask -TaskName 'MehrChatRelay' -Action $action -Trigger $trigger -Settings $settings -User 'SYSTEM' -RunLevel Highest
New-NetFirewallRule -DisplayName 'MehrChat Relay TCP' -Direction Inbound -Protocol TCP -LocalPort 8787 -Action Allow
Start-ScheduledTask -TaskName 'MehrChatRelay'
