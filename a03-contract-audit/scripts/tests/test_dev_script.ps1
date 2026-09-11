$ErrorActionPreference = 'Stop'

$projectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$devScript = Join-Path $projectRoot 'scripts\dev.ps1'

if (-not (Test-Path -LiteralPath $devScript -PathType Leaf)) {
    throw 'Missing scripts/dev.ps1'
}

$source = Get-Content -LiteralPath $devScript -Raw
if ($source -notmatch '\[int\]\$BackendPort\s*=\s*8000') {
    throw 'Backend default port must be 8000'
}
if ($source -notmatch '\[int\]\$FrontendPort\s*=\s*5173') {
    throw 'Frontend default port must be 5173'
}
if ($source -notmatch 'VITE_API_PROXY_TARGET') {
    throw 'Launcher must set VITE_API_PROXY_TARGET'
}

function Get-FreeTcpPort {
    $temporaryListener = [System.Net.Sockets.TcpListener]::new(
        [System.Net.IPAddress]::Loopback,
        0
    )
    $temporaryListener.Start()
    try {
        return ([System.Net.IPEndPoint]$temporaryListener.LocalEndpoint).Port
    }
    finally {
        $temporaryListener.Stop()
    }
}

$listener = [System.Net.Sockets.TcpListener]::new(
    [System.Net.IPAddress]::Loopback,
    0
)
$listener.Start()
try {
    $occupiedPort = ([System.Net.IPEndPoint]$listener.LocalEndpoint).Port
    $availableFrontendPort = Get-FreeTcpPort
    $output = & powershell -NoProfile -ExecutionPolicy Bypass -File $devScript `
        -CheckOnly -BackendPort $occupiedPort -FrontendPort $availableFrontendPort 2>&1
    if ($LASTEXITCODE -ne 2) {
        throw "Occupied port must return exit code 2, got $LASTEXITCODE"
    }
    if (($output -join "`n") -notmatch "Port $occupiedPort is already in use") {
        throw 'Occupied port message must include the port number'
    }
}
finally {
    $listener.Stop()
}


$fixtureRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("dev-script-test-{0}" -f [guid]::NewGuid())
$fixtureScriptRoot = Join-Path $fixtureRoot 'scripts'
$fixtureBackendRoot = Join-Path $fixtureRoot 'backend'
$fixturePythonRoot = Join-Path $fixtureBackendRoot '.venv\Scripts'
$fixtureFrontendRoot = Join-Path $fixtureRoot 'frontend'
$fixtureNodeModules = Join-Path $fixtureFrontendRoot 'node_modules'
$fixtureBin = Join-Path $fixtureRoot 'bin'
$fixtureDevScript = Join-Path $fixtureScriptRoot 'dev.ps1'
$frontendPidFile = Join-Path $fixtureRoot 'frontend.pid'
$frontendStub = Join-Path $fixtureRoot 'frontend-stub.ps1'
$fixtureNpm = Join-Path $fixtureBin 'npm.cmd'
$fixturePython = Join-Path $fixturePythonRoot 'python.exe'
$originalPath = $env:PATH
$frontendPid = $null
$frontendParentPid = $null
$failures = @()

try {
    @(
        $fixtureScriptRoot,
        $fixturePythonRoot,
        $fixtureNodeModules,
        $fixtureBin
    ) | ForEach-Object {
        New-Item -ItemType Directory -Path $_ -Force | Out-Null
    }

    Copy-Item -LiteralPath $devScript -Destination $fixtureDevScript
    Copy-Item -LiteralPath (Join-Path $env:SystemRoot 'System32\where.exe') -Destination $fixturePython

    @'
param([Parameter(Mandatory = $true)][string]$PidFile)
$PID | Set-Content -LiteralPath $PidFile -Encoding ascii
while ($true) {
    Start-Sleep -Milliseconds 100
}
'@ | Set-Content -LiteralPath $frontendStub -Encoding ascii

    @"
@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$frontendStub" -PidFile "$frontendPidFile"
"@ | Set-Content -LiteralPath $fixtureNpm -Encoding ascii

    $backendPort = Get-FreeTcpPort
    do {
        $frontendPort = Get-FreeTcpPort
    } while ($frontendPort -eq $backendPort)

    $env:PATH = "$fixtureBin;$originalPath"
    $failureOutput = & powershell -NoProfile -ExecutionPolicy Bypass -File $fixtureDevScript `
        -BackendPort $backendPort -FrontendPort $frontendPort 2>&1
    $launcherExitCode = $LASTEXITCODE

    $pidDeadline = [DateTime]::UtcNow.AddSeconds(3)
    while (-not (Test-Path -LiteralPath $frontendPidFile) -and [DateTime]::UtcNow -lt $pidDeadline) {
        Start-Sleep -Milliseconds 50
    }
    if (Test-Path -LiteralPath $frontendPidFile) {
        $frontendPid = [int](Get-Content -LiteralPath $frontendPidFile -Raw)
        $frontendProcessInfo = Get-CimInstance Win32_Process -Filter "ProcessId = $frontendPid"
        if ($null -ne $frontendProcessInfo) {
            $frontendParentPid = [int]$frontendProcessInfo.ParentProcessId
        }
    }

    if ($launcherExitCode -eq 0) {
        $failures += 'Backend immediate exit must make launcher return a non-zero exit code'
    }
    if ($null -eq $frontendPid) {
        $failures += 'Frontend fixture did not start, so cleanup behavior was not exercised'
    }
    elseif (Get-Process -Id $frontendPid -ErrorAction SilentlyContinue) {
        $failures += "Launcher left its frontend process running (PID $frontendPid)"
    }
    if (($failureOutput -join "`n") -match 'Backend started:') {
        $failures += 'Launcher must not report the backend as started after immediate exit'
    }
    if (($failureOutput -join "`n") -notmatch 'Backend process exited before becoming ready') {
        $failures += 'Launcher must explain that the backend exited before readiness'
    }
}
finally {
    $env:PATH = $originalPath
    if ($null -ne $frontendParentPid -and (Get-Process -Id $frontendParentPid -ErrorAction SilentlyContinue)) {
        & taskkill.exe /PID $frontendParentPid /T /F 2>$null | Out-Null
    }
    elseif ($null -ne $frontendPid -and (Get-Process -Id $frontendPid -ErrorAction SilentlyContinue)) {
        & taskkill.exe /PID $frontendPid /T /F 2>$null | Out-Null
    }
    if (Test-Path -LiteralPath $fixtureRoot) {
        $cleanupDeadline = [DateTime]::UtcNow.AddSeconds(3)
        do {
            try {
                Remove-Item -LiteralPath $fixtureRoot -Recurse -Force
            }
            catch [System.IO.IOException] {
                if ([DateTime]::UtcNow -ge $cleanupDeadline) {
                    throw
                }
                Start-Sleep -Milliseconds 100
            }
        } while (Test-Path -LiteralPath $fixtureRoot)
    }
}

if ($failures.Count -gt 0) {
    throw ($failures -join '; ')
}

Write-Output 'dev.ps1 contract passed'
