$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
$pythonPath = 'C:\Program Files\Python315\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) { throw 'Python not found. Edit pythonPath in start.ps1 to your Python installation.' }
$appEnvironment = Join-Path $env:LOCALAPPDATA 'RecoveryVault\venv'
if (-not (Test-Path -LiteralPath "$appEnvironment\Scripts\python.exe")) { & $pythonPath -m venv $appEnvironment; if ($LASTEXITCODE -ne 0) { throw 'Could not create Python environment.' } }
& "$appEnvironment\Scripts\python.exe" -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
& "$appEnvironment\Scripts\python.exe" recovery_app.py
