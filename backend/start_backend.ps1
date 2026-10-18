param([int]$Port=8765, [string]$Python='')
$ErrorActionPreference='Stop'
Push-Location -LiteralPath $PSScriptRoot
$previousPort = $env:VAI_PORT
try {
    $env:VAI_PORT=[string]$Port
    if (-not $Python) {
        foreach ($candidate in @('.venv-local/Scripts/python.exe', '.venv/Scripts/python.exe')) {
            if (Test-Path -LiteralPath $candidate) {
                & $candidate -c 'import fastapi, uvicorn, pydantic' 2>$null
                if ($LASTEXITCODE -eq 0) { $Python = $candidate; break }
            }
        }
    }
    if (-not $Python) { throw 'Run .\setup_backend.ps1 first, or supply -Python with a working backend interpreter.' }
    & $Python serve.py
    if ($LASTEXITCODE -ne 0) { throw 'Backend exited with an error. Check the message above.' }
} finally {
    $env:VAI_PORT = $previousPort
    Pop-Location
}
