param([int]$Port = 8766, [string]$Python = '')
$ErrorActionPreference = 'Stop'
# A dedicated port and run directory keep older RC-only services independent.
$generalHealth = $null
try { $generalHealth = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/health" -TimeoutSec 2 } catch { }
if ($generalHealth) {
    if ($generalHealth.templates -contains 'general_circuit') {
        Write-Host "General circuit backend is already available at http://127.0.0.1:$Port"
        return
    }
    throw "Port $Port is occupied by an older backend. Choose a different -Port."
}
$previousRunsDirectory = $env:VAI_RUNS_DIR
try {
    $env:VAI_RUNS_DIR = Join-Path $PSScriptRoot 'runs-general'
    Write-Host "Starting general circuit backend at http://127.0.0.1:$Port"
    & (Join-Path $PSScriptRoot 'start_backend.ps1') -Port $Port -Python $Python
} finally {
    $env:VAI_RUNS_DIR = $previousRunsDirectory
}
