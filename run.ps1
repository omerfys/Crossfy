$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
if (-not $ScriptDir) { $ScriptDir = Get-Location }
Set-Location $ScriptDir

$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"

$PythonExe = Join-Path $ScriptDir ".venv\Scripts\python.exe"
if (-not (Test-Path $PythonExe)) {
    $PythonExe = "python"
}

Write-Host "Starting Crossfy / Beamer (Dev Mode)..." -ForegroundColor Cyan
& $PythonExe (Join-Path $ScriptDir "start_dev.py") @args
