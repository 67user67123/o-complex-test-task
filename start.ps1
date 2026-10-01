param([int]$Port = 8000)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$servicePython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $servicePython)) {
    throw 'Сначала создайте .venv и установите зависимости по README.md.'
}
& $servicePython -m uvicorn app.main:app --host 127.0.0.1 --port $Port
