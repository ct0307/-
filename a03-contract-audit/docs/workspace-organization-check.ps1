[CmdletBinding()]
param()

$repoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$errors = [System.Collections.Generic.List[string]]::new()

$required = @(
    'README.md',
    'AGENTS.md',
    'a03-contract-audit',
    'a03-contract-audit/docs/superpowers/specs',
    'a03-contract-audit/docs/workspace-organization-check.ps1',
    'references/README.md',
    'references/浙江省外包赛-2026赛题手册.pdf',
    'references/浙江省外包赛-2026赛题手册综合分析.docx',
    'references/A03企业合同合规审查系统实施方案.docx',
    'deliverables/README.md'
)

$forbiddenPaths = @(
    '浙江省外包赛-2026赛题手册.pdf',
    '浙江省外包赛-2026赛题手册综合分析.docx',
    'A03企业合同合规审查系统实施方案.docx',
    'a03-demo',
    'archive/a03-demo'
)

foreach ($relativePath in $required) {
    if (-not (Test-Path -LiteralPath (Join-Path $repoRoot $relativePath))) {
        $errors.Add("缺少目标路径：$relativePath")
    }
}

foreach ($relativePath in $forbiddenPaths) {
    if (Test-Path -LiteralPath (Join-Path $repoRoot $relativePath)) {
        $errors.Add("废弃路径仍存在：$relativePath")
    }
}

$ignored = @(
    '.planning',
    'a03-contract-audit/outputs',
    'a03-contract-audit/docs/project-overview/rendered'
)
foreach ($relativePath in $ignored) {
    $sentinelPath = "$relativePath/.workspace-organization-check"
    & git -C $repoRoot check-ignore -q --no-index -- $sentinelPath
    if ($LASTEXITCODE -ne 0) {
        $errors.Add("未被 Git 忽略：$relativePath")
    }
}

$deletedFiles = [System.Collections.Generic.HashSet[string]]::new(
    [System.StringComparer]::OrdinalIgnoreCase
)
@(& git -C $repoRoot -c core.quotepath=false ls-files --deleted) |
    ForEach-Object { [void]$deletedFiles.Add($_) }
$trackedFiles = @(& git -C $repoRoot -c core.quotepath=false ls-files) |
    Where-Object { -not $deletedFiles.Contains($_) }

$forbiddenTrackedPrefixes = @(
    'archive/a03-demo/',
    'a03-contract-audit/docs/project-overview/rendered/',
    'a03-contract-audit/docs/superpowers/plans/'
)
foreach ($prefix in $forbiddenTrackedPrefixes) {
    $matches = @($trackedFiles | Where-Object { $_.StartsWith($prefix) })
    if ($matches.Count -gt 0) {
        $errors.Add("废弃资产仍被 Git 跟踪：$prefix`n$($matches -join "`n")")
    }
}

$textExtensions = @('.css', '.html', '.js', '.json', '.md', '.mjs', '.ps1', '.py', '.ts', '.tsx', '.vue', '.yml', '.yaml')
$historicalReferencePrefixes = @(
    'a03-contract-audit/docs/superpowers/specs/'
)
$historicalReferenceFiles = @(
    'a03-contract-audit/PROGRESS.md'
)
$checkScript = 'a03-contract-audit/docs/workspace-organization-check.ps1'
$oldReferences = [System.Collections.Generic.List[string]]::new()

foreach ($relativePath in $trackedFiles) {
    if ($relativePath -eq $checkScript) { continue }
    if ($historicalReferenceFiles -contains $relativePath) { continue }
    if ($historicalReferencePrefixes | Where-Object { $relativePath.StartsWith($_) }) { continue }
    if ([IO.Path]::GetExtension($relativePath).ToLowerInvariant() -notin $textExtensions) { continue }

    $absolutePath = Join-Path $repoRoot $relativePath
    if (-not (Test-Path -LiteralPath $absolutePath -PathType Leaf)) { continue }
    $lineNumber = 0
    foreach ($line in [IO.File]::ReadAllLines($absolutePath)) {
        $lineNumber++
        if ($line.Contains('archive/a03-demo/')) {
            $oldReferences.Add("${relativePath}:${lineNumber}:$line")
        }
        foreach ($fileName in @(
            '浙江省外包赛-2026赛题手册.pdf',
            '浙江省外包赛-2026赛题手册综合分析.docx',
            'A03企业合同合规审查系统实施方案.docx'
        )) {
            if (
                $line.Contains($fileName) -and
                -not $relativePath.StartsWith('references/') -and
                -not $line.Contains("references/$fileName")
            ) {
                $oldReferences.Add("${relativePath}:${lineNumber}:$line")
            }
        }
    }
}

if ($oldReferences.Count -gt 0) {
    $errors.Add("发现废弃路径引用：`n$($oldReferences -join "`n")")
}

if ($errors.Count -gt 0) {
    $errors | ForEach-Object { Write-Error $_ }
    exit 1
}

Write-Output 'PASS workspace organization'
exit 0
