param([string]$Python = 'python')
$ErrorActionPreference = 'Stop'
Push-Location -LiteralPath $PSScriptRoot
try {
    # venv paths are machine-specific. Keep any copied .venv intact.
    $localPython = Join-Path $PSScriptRoot '.venv-local\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $localPython)) {
        & $Python -m venv .venv-local
        if ($LASTEXITCODE -ne 0) { throw 'Cannot create the local Python environment.' }
    }
    & $localPython -m pip install -r requirements-dev.txt
    if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
    & $localPython -c 'import fastapi, uvicorn, pydantic; print("Backend environment ready")'
    if ($LASTEXITCODE -ne 0) { throw 'Backend environment check failed.' }
} finally {
    Pop-Location
}
