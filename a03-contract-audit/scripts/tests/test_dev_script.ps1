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

$listener = [System.Net.Sockets.TcpListener]::new(
    [System.Net.IPAddress]::Loopback,
    0
)
$listener.Start()
try {
    $occupiedPort = ([System.Net.IPEndPoint]$listener.LocalEndpoint).Port
    $output = & powershell -NoProfile -ExecutionPolicy Bypass -File $devScript `
        -CheckOnly -BackendPort $occupiedPort -FrontendPort 65534 2>&1
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

Write-Output 'dev.ps1 contract passed'
