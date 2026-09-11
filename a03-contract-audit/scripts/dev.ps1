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
$startupTimeout = [TimeSpan]::FromSeconds(30)

function Assert-PortAvailable([int]$Port) {
    $owner = Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue |
        Select-Object -First 1 -ExpandProperty OwningProcess
    if ($null -ne $owner) {
        Write-Output "Port $Port is already in use by PID $owner. Stop that service or use the existing instance."
        exit 2
    }
}

function Test-ProcessRunning([System.Diagnostics.Process]$Process) {
    if ($null -eq $Process) {
        return $false
    }
    $Process.Refresh()
    return -not $Process.HasExited
}

function Test-BackendHealth([string]$BaseUrl) {
    try {
        $response = Invoke-WebRequest -Uri "$BaseUrl/health/live" -UseBasicParsing -TimeoutSec 1
        return $response.StatusCode -ge 200 -and $response.StatusCode -lt 300
    }
    catch {
        return $false
    }
}

function Test-TcpPortListening([int]$Port) {
    $client = [System.Net.Sockets.TcpClient]::new()
    $connect = $null
    try {
        $connect = $client.BeginConnect('127.0.0.1', $Port, $null, $null)
        if (-not $connect.AsyncWaitHandle.WaitOne(200)) {
            return $false
        }
        $client.EndConnect($connect)
        return $client.Connected
    }
    catch {
        return $false
    }
    finally {
        if ($null -ne $connect) {
            $connect.AsyncWaitHandle.Close()
        }
        $client.Close()
    }
}

function Stop-StartedProcess([System.Diagnostics.Process]$Process) {
    if (Test-ProcessRunning $Process) {
        & taskkill.exe /PID $Process.Id /T /F 2>$null | Out-Null
    }
}

if ($BackendPort -eq $FrontendPort) {
    Write-Output 'BackendPort and FrontendPort must be different. Choose a separate port for each service.'
    exit 2
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
$frontendProcess = $null
$previousProxyTarget = $env:VITE_API_PROXY_TARGET
try {
    $backendProcess = Start-Process -FilePath $python `
        -ArgumentList @('-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', "$BackendPort") `
        -WorkingDirectory $backendRoot -WindowStyle Hidden -PassThru

    $env:VITE_API_PROXY_TARGET = $backendTarget
    $frontendProcess = Start-Process -FilePath $npm.Source `
        -ArgumentList @('run', 'dev', '--', '--host', '127.0.0.1', '--port', "$FrontendPort", '--strictPort') `
        -WorkingDirectory $frontendRoot -WindowStyle Hidden -PassThru

    $deadline = [DateTime]::UtcNow.Add($startupTimeout)
    $backendReady = $false
    $frontendReady = $false
    while ([DateTime]::UtcNow -lt $deadline) {
        if (-not (Test-ProcessRunning $backendProcess)) {
            throw "Backend process exited before becoming ready. Check backend configuration and logs. Exit code: $($backendProcess.ExitCode)."
        }
        if (-not (Test-ProcessRunning $frontendProcess)) {
            throw "Frontend process exited before opening port $FrontendPort. Check the Vite startup output. Exit code: $($frontendProcess.ExitCode)."
        }

        $backendReady = Test-BackendHealth $backendTarget
        $frontendReady = Test-TcpPortListening $FrontendPort
        if ($backendReady -and $frontendReady) {
            break
        }
        Start-Sleep -Milliseconds 100
    }

    if (-not $backendReady -or -not $frontendReady) {
        $missing = @()
        if (-not $backendReady) {
            $missing += "backend health endpoint $backendTarget/health/live"
        }
        if (-not $frontendReady) {
            $missing += "frontend port $FrontendPort"
        }
        throw "Timed out waiting for $($missing -join ' and '). Check service logs and configuration."
    }
}
catch {
    Stop-StartedProcess $frontendProcess
    Stop-StartedProcess $backendProcess
    Write-Output "Failed to start the development services. $($_.Exception.Message)"
    exit 4
}
finally {
    $env:VITE_API_PROXY_TARGET = $previousProxyTarget
}

Write-Output "Backend started: $backendTarget (PID $($backendProcess.Id))"
Write-Output "Frontend started: http://127.0.0.1:$FrontendPort (PID $($frontendProcess.Id))"
Write-Output "Frontend API proxy: $backendTarget"
Write-Output 'Restart the backend after changing backend/.env.'
