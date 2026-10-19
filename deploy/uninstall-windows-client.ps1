$ErrorActionPreference='Stop'
$target=Join-Path $env:LOCALAPPDATA 'Programs\MehrChat'
if(Test-Path $target){Remove-Item $target -Recurse -Force}
$link=Join-Path ([Environment]::GetFolderPath('Desktop')) 'MehrChat.lnk'
if(Test-Path $link){Remove-Item $link}
Write-Host 'Account data in APPDATA/MehrChat has been preserved.'
