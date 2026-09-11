[CmdletBinding()]
param(
    [switch]$CheckOnly,
    [int]$BackendPort = 8000,
    [int]$FrontendPort = 5173
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$backendRoot = Join-Path $projectRoot 'backend'
$frontendRoot = Join-Path $projectRoot 'frontend'
$python = Join-Path $backendRoot '.venv\Scripts\python.exe'

function Assert-PortAvailable([int]$Port) {
    $owner = Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue |
        Select-Object -First 1 -ExpandProperty OwningProcess
    if ($null -ne $owner) {
        Write-Output "Port $Port is already in use by PID $owner. Stop that service or use the existing instance."
        exit 2
    }
}

Assert-PortAvailable $BackendPort
Assert-PortAvailable $FrontendPort

if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    Write-Output "Backend virtual environment is missing: $python"
    exit 3
}
$npm = Get-Command npm.cmd -ErrorAction SilentlyContinue
if ($null -eq $npm) {
    Write-Output 'npm.cmd is not available on PATH.'
    exit 3
}
if (-not (Test-Path -LiteralPath (Join-Path $frontendRoot 'node_modules') -PathType Container)) {
    Write-Output 'Frontend dependencies are missing. Run npm install after dependency review.'
    exit 3
}

$backendTarget = "http://127.0.0.1:$BackendPort"
if ($CheckOnly) {
    Write-Output "Development ports are available. Backend=$backendTarget Frontend=http://127.0.0.1:$FrontendPort"
    exit 0
}

$backendProcess = $null
$previousProxyTarget = $env:VITE_API_PROXY_TARGET
try {
    $backendProcess = Start-Process -FilePath $python `
        -ArgumentList @('-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', "$BackendPort") `
        -WorkingDirectory $backendRoot -WindowStyle Hidden -PassThru

    $env:VITE_API_PROXY_TARGET = $backendTarget
    $frontendProcess = Start-Process -FilePath $npm.Source `
        -ArgumentList @('run', 'dev', '--', '--host', '127.0.0.1', '--port', "$FrontendPort") `
        -WorkingDirectory $frontendRoot -WindowStyle Hidden -PassThru
}
catch {
    if ($null -ne $backendProcess -and -not $backendProcess.HasExited) {
        Stop-Process -Id $backendProcess.Id
    }
    Write-Output 'Failed to start the development services.'
    exit 4
}
finally {
    $env:VITE_API_PROXY_TARGET = $previousProxyTarget
}

Write-Output "Backend started: $backendTarget (PID $($backendProcess.Id))"
Write-Output "Frontend started: http://127.0.0.1:$FrontendPort (PID $($frontendProcess.Id))"
Write-Output "Frontend API proxy: $backendTarget"
Write-Output 'Restart the backend after changing backend/.env.'
