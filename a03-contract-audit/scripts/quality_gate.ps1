[CmdletBinding()]
param(
    [switch]$IncludeE2E,
    [string]$ContractSetDir
)

$projectRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $projectRoot 'backend\.venv\Scripts\python.exe'

if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    Write-Error "未找到后端虚拟环境 Python：$python"
    exit 3
}

$arguments = @((Join-Path $PSScriptRoot 'quality_gate.py'))
if ($IncludeE2E) {
    $arguments += '--include-e2e'
}
if ($ContractSetDir) {
    $arguments += @('--contract-set-dir', $ContractSetDir)
}

& $python @arguments
exit $LASTEXITCODE
