[CmdletBinding()]
param()

$repoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$errors = [System.Collections.Generic.List[string]]::new()

$required = @(
    'README.md',
    'AGENTS.md',
    'a03-contract-audit',
    'references/README.md',
    'references/浙江省外包赛-2026赛题手册.pdf',
    'references/浙江省外包赛-2026赛题手册综合分析.docx',
    'references/A03企业合同合规审查系统实施方案.docx',
    'deliverables/README.md',
    'archive/a03-demo/README.md',
    'archive/a03-demo/app.js',
    'archive/a03-demo/index.html',
    'archive/a03-demo/styles.css'
)

$forbidden = @(
    '浙江省外包赛-2026赛题手册.pdf',
    '浙江省外包赛-2026赛题手册综合分析.docx',
    'A03企业合同合规审查系统实施方案.docx',
    'a03-demo'
)

foreach ($relativePath in $required) {
    if (-not (Test-Path -LiteralPath (Join-Path $repoRoot $relativePath))) {
        $errors.Add("缺少目标路径：$relativePath")
    }
}

foreach ($relativePath in $forbidden) {
    if (Test-Path -LiteralPath (Join-Path $repoRoot $relativePath)) {
        $errors.Add("旧路径仍存在：$relativePath")
    }
}

$ignored = @('.planning', 'a03-contract-audit/outputs')
foreach ($relativePath in $ignored) {
    & git -C $repoRoot check-ignore -q -- $relativePath
    if ($LASTEXITCODE -ne 0) {
        $errors.Add("未被 Git 忽略：$relativePath")
    }
}

$excluded = @(
    ':!a03-contract-audit/docs/superpowers/specs/2026-09-04-workspace-organization-design.md',
    ':!a03-contract-audit/docs/superpowers/plans/2026-09-04-workspace-organization.md'
)
$patterns = @(
    '浙江省外包赛-2026赛题手册.pdf',
    '浙江省外包赛-2026赛题手册综合分析.docx',
    'A03企业合同合规审查系统实施方案.docx',
    'a03-demo/'
)
$oldReferences = @()
foreach ($pattern in $patterns) {
    $matches = @(& git -C $repoRoot grep -n -F -- $pattern -- @excluded 2>$null)
    foreach ($match in $matches) {
        if ($match -notmatch 'references/' -and $match -notmatch 'archive/a03-demo/') {
            $oldReferences += $match
        }
    }
}
if ($oldReferences.Count -gt 0) {
    $errors.Add("发现旧路径引用：`n$($oldReferences -join "`n")")
}

if ($errors.Count -gt 0) {
    $errors | ForEach-Object { Write-Error $_ }
    exit 1
}

Write-Output 'PASS workspace organization'
exit 0
