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

$samePort = Get-FreeTcpPort
$samePortOutput = & powershell -NoProfile -ExecutionPolicy Bypass -File $devScript `
    -CheckOnly -BackendPort $samePort -FrontendPort $samePort 2>&1
if ($LASTEXITCODE -eq 0) {
    throw 'CheckOnly must reject identical backend and frontend ports'
}
if (($samePortOutput -join "`n") -notmatch 'BackendPort and FrontendPort must be different') {
    throw 'Identical-port rejection must explain how to choose different ports'
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
$frontendParentPidFile = Join-Path $fixtureRoot 'frontend-parent.pid'
$frontendArgsFile = Join-Path $fixtureRoot 'frontend.args'
$backendPidFile = Join-Path $fixtureRoot 'backend.pid'
$frontendStub = Join-Path $fixtureRoot 'frontend-stub.ps1'
$fixtureNpm = Join-Path $fixtureBin 'npm.cmd'
$fixturePython = Join-Path $fixturePythonRoot 'python.exe'
$originalPath = $env:PATH
$originalFrontendReadyFile = $env:DEV_TEST_FRONTEND_READY_FILE
$originalBackendPidFile = $env:DEV_TEST_BACKEND_PID_FILE
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
    $backendStubSource = @'
using System;
using System.Diagnostics;
using System.IO;
using System.Threading;

public static class BackendStub
{
    public static int Main()
    {
        var readyFile = Environment.GetEnvironmentVariable("DEV_TEST_FRONTEND_READY_FILE");
        var pidFile = Environment.GetEnvironmentVariable("DEV_TEST_BACKEND_PID_FILE");
        File.WriteAllText(pidFile, Process.GetCurrentProcess().Id.ToString());
        var deadline = DateTime.UtcNow.AddSeconds(5);
        while (!File.Exists(readyFile) && DateTime.UtcNow < deadline)
        {
            Thread.Sleep(20);
        }
        return File.Exists(readyFile) ? 23 : 24;
    }
}
'@
    Add-Type -TypeDefinition $backendStubSource -OutputAssembly $fixturePython `
        -OutputType ConsoleApplication

    @'
param(
    [Parameter(Mandatory = $true)][string]$PidFile,
    [Parameter(Mandatory = $true)][string]$ParentPidFile
)
$PID | Set-Content -LiteralPath $PidFile -Encoding ascii
(Get-CimInstance Win32_Process -Filter "ProcessId = $PID").ParentProcessId |
    Set-Content -LiteralPath $ParentPidFile -Encoding ascii
while ($true) {
    Start-Sleep -Milliseconds 100
}
'@ | Set-Content -LiteralPath $frontendStub -Encoding ascii

    @"
@echo off
echo %*>"$frontendArgsFile"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$frontendStub" -PidFile "$frontendPidFile" -ParentPidFile "$frontendParentPidFile"
"@ | Set-Content -LiteralPath $fixtureNpm -Encoding ascii

    $env:DEV_TEST_FRONTEND_READY_FILE = $frontendPidFile
    $env:DEV_TEST_BACKEND_PID_FILE = $backendPidFile
    $env:PATH = "$fixtureBin;$originalPath"

    $sameStartupPort = Get-FreeTcpPort
    $sameStartupOutput = & powershell -NoProfile -ExecutionPolicy Bypass -File $fixtureDevScript `
        -BackendPort $sameStartupPort -FrontendPort $sameStartupPort 2>&1
    if ($LASTEXITCODE -eq 0) {
        $failures += 'Startup must reject identical backend and frontend ports'
    }
    if (($sameStartupOutput -join "`n") -notmatch 'BackendPort and FrontendPort must be different') {
        $failures += 'Startup identical-port rejection must explain how to choose different ports'
    }
    if (Test-Path -LiteralPath $backendPidFile) {
        $failures += 'Identical-port rejection must happen before starting the backend'
    }
    if (Test-Path -LiteralPath $frontendPidFile) {
        $failures += 'Identical-port rejection must happen before starting the frontend'
    }

    Remove-Item -LiteralPath $backendPidFile, $frontendPidFile, $frontendParentPidFile, $frontendArgsFile `
        -Force -ErrorAction SilentlyContinue

    $backendPort = Get-FreeTcpPort
    do {
        $frontendPort = Get-FreeTcpPort
    } while ($frontendPort -eq $backendPort)

    $failureOutput = & powershell -NoProfile -ExecutionPolicy Bypass -File $fixtureDevScript `
        -BackendPort $backendPort -FrontendPort $frontendPort 2>&1
    $launcherExitCode = $LASTEXITCODE

    $pidDeadline = [DateTime]::UtcNow.AddSeconds(3)
    while (-not (Test-Path -LiteralPath $frontendPidFile) -and [DateTime]::UtcNow -lt $pidDeadline) {
        Start-Sleep -Milliseconds 50
    }
    if (Test-Path -LiteralPath $frontendPidFile) {
        $frontendPid = [int](Get-Content -LiteralPath $frontendPidFile -Raw)
    }
    if (Test-Path -LiteralPath $frontendParentPidFile) {
        $frontendParentPid = [int](Get-Content -LiteralPath $frontendParentPidFile -Raw)
    }

    if ($launcherExitCode -eq 0) {
        $failures += 'Backend immediate exit must make launcher return a non-zero exit code'
    }
    if (-not (Test-Path -LiteralPath $backendPidFile)) {
        $failures += 'Backend fixture did not start'
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
    if (($failureOutput -join "`n") -notmatch 'Exit code: 23') {
        $failures += 'Backend fixture must exit only after observing frontend readiness'
    }
    if (-not (Test-Path -LiteralPath $frontendArgsFile)) {
        $failures += 'Frontend fixture did not capture Vite arguments'
    }
    elseif ((Get-Content -LiteralPath $frontendArgsFile -Raw) -notmatch '(?:^|\s)--strictPort(?:\s|$)') {
        $failures += 'Launcher must pass --strictPort to Vite'
    }
}
finally {
    $env:PATH = $originalPath
    $env:DEV_TEST_FRONTEND_READY_FILE = $originalFrontendReadyFile
    $env:DEV_TEST_BACKEND_PID_FILE = $originalBackendPidFile
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
