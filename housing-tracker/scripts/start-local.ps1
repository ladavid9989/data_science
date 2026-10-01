param(
    [int]$Port = 8502,
    [string]$PythonExecutable,
    [string]$DatabasePath
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
if (-not $PythonExecutable) {
    $localEnvironment = Join-Path $projectRoot '.venv/Scripts/python.exe'
    $workspaceEnvironment = Join-Path $projectRoot '../../.runtime/venv/Scripts/python.exe'
    if (Test-Path -LiteralPath $localEnvironment) {
        $PythonExecutable = (Resolve-Path -LiteralPath $localEnvironment).Path
    } elseif (Test-Path -LiteralPath $workspaceEnvironment) {
        $PythonExecutable = (Resolve-Path -LiteralPath $workspaceEnvironment).Path
    } else {
        $PythonExecutable = 'python'
    }
}
if ($DatabasePath) { $env:HOUSING_DB_PATH = $DatabasePath }
Push-Location $projectRoot
try {
    & $PythonExecutable -m tracker.cli sync
    if ($LASTEXITCODE -ne 0) { Write-Warning 'Cloud sync unavailable; opening existing local observations.' }
    Write-Host "Open http://127.0.0.1:$Port"
    & $PythonExecutable -m streamlit run streamlit_app.py --server.address 127.0.0.1 --server.port $Port --server.headless true --browser.gatherUsageStats false
} finally {
    Pop-Location
}
