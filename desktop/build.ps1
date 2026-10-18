param(
    [string]$Python = 'python',
    [string]$OutputDirectory = "$PSScriptRoot\release"
)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$frontendRoot = Join-Path $projectRoot 'frontend'
$venvPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'

if (-not (Test-Path -LiteralPath $venvPython)) {
    & $Python -m venv (Join-Path $PSScriptRoot '.venv')
    if ($LASTEXITCODE -ne 0) { throw 'Failed to create the desktop Python environment.' }
}
& $venvPython -m pip install -r (Join-Path $PSScriptRoot 'requirements.txt')
if ($LASTEXITCODE -ne 0) { throw 'Desktop dependency installation failed.' }

Push-Location $frontendRoot
try {
    if (-not (Test-Path -LiteralPath 'node_modules\vite')) { throw 'Run npm ci in frontend first.' }
    & node --test tests/*.test.mjs
    if ($LASTEXITCODE -ne 0) { throw 'Frontend tests failed.' }
    & node node_modules\typescript\bin\tsc --noEmit
    if ($LASTEXITCODE -ne 0) { throw 'TypeScript validation failed.' }
    & node node_modules\vite\bin\vite.js build
    if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed.' }
} finally { Pop-Location }

& $venvPython -m unittest discover -s (Join-Path $PSScriptRoot 'tests') -v
if ($LASTEXITCODE -ne 0) { throw 'Desktop tests failed.' }

& $venvPython -m PyInstaller --noconfirm --clean --onefile --windowed `
    --name AutoCadence `
    --version-file (Join-Path $PSScriptRoot 'version_info.txt') `
    --icon (Join-Path $PSScriptRoot 'app.ico') `
    --distpath $OutputDirectory `
    --workpath (Join-Path $PSScriptRoot 'build') `
    --specpath $PSScriptRoot `
    --add-data "$frontendRoot\dist;frontend" `
    --exclude-module PyQt5 --exclude-module PyQt6 --exclude-module PySide2 --exclude-module PySide6 `
    (Join-Path $PSScriptRoot 'main.py')
if ($LASTEXITCODE -ne 0) { throw 'EXE packaging failed.' }
Write-Output "EXE ready: $(Join-Path $OutputDirectory 'AutoCadence.exe')"
