$ErrorActionPreference = 'Stop'
$projectDirectory = $PSScriptRoot
Set-Location -LiteralPath $projectDirectory
$pythonExecutable = Join-Path $projectDirectory '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonExecutable)) {
    python -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Installare Python 3.11 o successivo, con supporto Tkinter.' }
}
& $pythonExecutable -c 'import requests, keyring'
if ($LASTEXITCODE -ne 0) {
    & $pythonExecutable -m pip install -r requirements.txt
    if ($LASTEXITCODE -ne 0) { throw 'Installazione dipendenze non riuscita.' }
}
& $pythonExecutable -m moretta gui
