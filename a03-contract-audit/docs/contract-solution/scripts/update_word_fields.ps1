param(
    [string]$DocxPath = "",
    [string]$PdfPath = ""
)

$ErrorActionPreference = "Stop"

$solutionRoot = Split-Path -Parent $PSScriptRoot
if ([string]::IsNullOrWhiteSpace($DocxPath)) {
    $docxCandidates = @(Get-ChildItem -LiteralPath $solutionRoot -Filter "*.docx" -File)
    if ($docxCandidates.Count -ne 1) {
        throw "Expected exactly one DOCX in $solutionRoot, found $($docxCandidates.Count)"
    }
    $DocxPath = $docxCandidates[0].FullName
}
if ([string]::IsNullOrWhiteSpace($PdfPath)) {
    $PdfPath = [System.IO.Path]::ChangeExtension($DocxPath, ".pdf")
}

$resolvedDocx = (Resolve-Path -LiteralPath $DocxPath).Path
$resolvedPdf = [System.IO.Path]::GetFullPath($PdfPath)
if ([System.IO.Path]::GetExtension($resolvedDocx) -ne ".docx") {
    throw "Input must be a DOCX: $resolvedDocx"
}
if ([System.IO.Path]::GetExtension($resolvedPdf) -ne ".pdf") {
    throw "Output must be a PDF: $resolvedPdf"
}

$word = $null
$document = $null
try {
    $word = New-Object -ComObject Word.Application
    $word.Visible = $false
    $word.DisplayAlerts = 0

    $document = $word.Documents.Open($resolvedDocx, $false, $false)

    foreach ($toc in $document.TablesOfContents) {
        $toc.Update()
    }
    $document.Fields.Update() | Out-Null

    foreach ($section in $document.Sections) {
        foreach ($header in $section.Headers) {
            if ($header.Exists) {
                $header.Range.Fields.Update() | Out-Null
            }
        }
        foreach ($footer in $section.Footers) {
            if ($footer.Exists) {
                $footer.Range.Fields.Update() | Out-Null
            }
        }
    }

    $document.Repaginate()
    $pageCount = $document.ComputeStatistics(2)
    $document.Save()

    $wdExportFormatPDF = 17
    $wdExportOptimizeForPrint = 0
    $wdExportAllDocument = 0
    $wdExportDocumentContent = 0
    $wdExportCreateHeadingBookmarks = 1
    $document.ExportAsFixedFormat(
        $resolvedPdf,
        $wdExportFormatPDF,
        $false,
        $wdExportOptimizeForPrint,
        $wdExportAllDocument,
        1,
        1,
        $wdExportDocumentContent,
        $true,
        $true,
        $wdExportCreateHeadingBookmarks,
        $true,
        $true,
        $false
    )

    $document.Save()
    Write-Output "updated=$resolvedDocx"
    Write-Output "exported=$resolvedPdf"
    Write-Output "pages=$pageCount"
}
finally {
    if ($null -ne $document) {
        $document.Close($false)
        [void][System.Runtime.InteropServices.Marshal]::FinalReleaseComObject($document)
    }
    if ($null -ne $word) {
        $word.Quit()
        [void][System.Runtime.InteropServices.Marshal]::FinalReleaseComObject($word)
    }
    [GC]::Collect()
    [GC]::WaitForPendingFinalizers()
}
