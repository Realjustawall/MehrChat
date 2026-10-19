param([switch]$NoLaunch)
$ErrorActionPreference='Stop'
$root=Split-Path $PSScriptRoot -Parent
$target=Join-Path $env:LOCALAPPDATA 'Programs\MehrChat'
New-Item -ItemType Directory -Force -Path $target | Out-Null
Copy-Item (Join-Path $root 'dist\MehrChat\*') $target -Recurse -Force
$shell=New-Object -ComObject WScript.Shell
$link=$shell.CreateShortcut((Join-Path ([Environment]::GetFolderPath('Desktop')) 'MehrChat.lnk'))
$link.TargetPath=Join-Path $target 'MehrChat.exe';$link.WorkingDirectory=$target;$link.Save()
if (!$NoLaunch) { Start-Process (Join-Path $target 'MehrChat.exe') }
