$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
$root = (Get-Location).Path
$python = Join-Path $root '.venv\Scripts\python.exe'
if (!(Test-Path $python)) { py -3 -m venv .venv }
& $python -m pip install -r requirements-server.txt
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed' }
& $python -m mehrchat.server --data (Join-Path $env:ProgramData 'MehrRelay') --port 8787
