[CmdletBinding()]
param(
    [ValidateRange(1, 139)]
    [int]$MaxPages = 139,
    [ValidateRange(0.5, 30.0)]
    [double]$DelaySeconds = 2.5,
    [switch]$InstallDependencies,
    [switch]$NewBatch
)

$ErrorActionPreference = "Stop"
$PSNativeCommandUseErrorActionPreference = $false
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $Root

$CaptureDir = Join-Path $Root "data/supplier_captures/dgdeler"
$PagesDir = Join-Path $CaptureDir "pages"
$CatalogPath = Join-Path $CaptureDir "catalog.json"
$BatchPath = Join-Path $CaptureDir "listing_batch.json"
$PageOnePath = Join-Path $PagesDir "page_001.json"
$SnapshotPath = Join-Path $Root "docs/supplier-research/dgdeler_product_list_page1_2026-10-28.json"
$DatabasePath = Join-Path $Root ".local/supplier_catalog.sqlite3"
$KnowledgeDB = Join-Path $Root ".local/huangren.sqlite3"
$MarkdownDir = Join-Path $CaptureDir "details_markdown"
$ExportDir = Join-Path $CaptureDir "exports"

function Invoke-PythonStep {
    param(
        [Parameter(Mandatory = $true)][string]$Label,
        [Parameter(Mandatory = $true)][string[]]$Arguments
    )
    Write-Host ""
    Write-Host "===== $Label =====" -ForegroundColor Cyan
    & python @Arguments 2>&1 | Out-Host
    $code = $LASTEXITCODE
    Write-Host "Exit code: $code"
    return $code
}

if ($InstallDependencies) {
    $installCode = Invoke-PythonStep -Label "Install dependencies" -Arguments @(
        "-m", "pip", "install", "-r", "requirements.txt", "-r", "requirements-supplier-capture.txt"
    )
    if ($installCode -ne 0) { exit $installCode }
    $browserCode = Invoke-PythonStep -Label "Install Chromium" -Arguments @(
        "-m", "playwright", "install", "chromium"
    )
    if ($browserCode -ne 0) { exit $browserCode }
}

New-Item -ItemType Directory -Force -Path $CaptureDir | Out-Null
if (-not (Test-Path $CatalogPath)) {
    if (Test-Path $PageOnePath) {
        $null = Invoke-PythonStep -Label "Rebuild catalog from existing checkpoints" -Arguments @(
            "scripts/supplier_catalog_capture.py", "audit", "--output", $CaptureDir
        )
    }
    else {
        $seedCode = Invoke-PythonStep -Label "Seed first-page checkpoint" -Arguments @(
            "scripts/seed_supplier_capture.py", "--output", $CaptureDir
        )
        if ($seedCode -ne 0) { exit $seedCode }
    }
}

Write-Host ""
Write-Host "The capture opens a separate Chromium profile. Log in and complete any site-provided checks in that window; the script will not bypass them." -ForegroundColor Yellow
$listingArgs = @(
    "scripts/supplier_catalog_capture.py", "listing",
    "--max-pages", "$MaxPages", "--delay", "$DelaySeconds"
)
if ($NewBatch -or -not (Test-Path $BatchPath)) {
    $listingArgs += "--refresh-existing"
}
$listingCode = Invoke-PythonStep -Label "Capture listing pages" -Arguments $listingArgs

$listingAuditCode = Invoke-PythonStep -Label "Audit listing checkpoints" -Arguments @(
    "scripts/supplier_catalog_capture.py", "audit", "--output", $CaptureDir
)

$detailCode = 1
if (Test-Path $CatalogPath) {
    $detailCode = Invoke-PythonStep -Label "Capture product details" -Arguments @(
        "scripts/supplier_catalog_capture.py", "details", "--delay", "$DelaySeconds", "--retries", "2"
    )
}
else {
    Write-Host "No catalog.json was produced; details capture is skipped." -ForegroundColor Red
}

$finalCaptureAuditCode = Invoke-PythonStep -Label "Build final capture audits" -Arguments @(
    "scripts/supplier_catalog_capture.py", "audit", "--output", $CaptureDir
)

$syncCode = Invoke-PythonStep -Label "Sync SQLite and export CSV" -Arguments @(
    "scripts/sync_supplier_catalog_db.py", "sync",
    "--capture-dir", $CaptureDir,
    "--snapshot-json", $SnapshotPath,
    "--database", $DatabasePath,
    "--export-dir", $ExportDir,
    "--require-details"
)

$databaseAuditCode = Invoke-PythonStep -Label "Require database and collection completeness" -Arguments @(
    "scripts/sync_supplier_catalog_db.py", "audit",
    "--database", $DatabasePath, "--require-complete", "--require-details"
)

$independentCode = Invoke-PythonStep -Label "Independently verify capture source files" -Arguments @(
    "scripts/verify_supplier_pipeline.py", "--capture-dir", $CaptureDir,
    "--require-details", "--expect-status", "complete",
    "--report", (Join-Path $CaptureDir "independent_validation.json")
)

$knowledgeCode = 2
if (Test-Path $MarkdownDir) {
    $markdownFiles = @(Get-ChildItem -Path $MarkdownDir -Filter "*.md" -File)
    if ($markdownFiles.Count -gt 0) {
        $knowledgeCode = Invoke-PythonStep -Label "Index original detail documents in V13 (unverified)" -Arguments @(
            "scripts/import_supplier_capture_v13.py", "--capture-dir", $MarkdownDir,
            "--database", $KnowledgeDB
        )
    }
}
if ($knowledgeCode -eq 2) {
    Write-Host "No detail Markdown documents available to index in V13." -ForegroundColor Yellow
}

Write-Host ""
Write-Host "===== Output locations =====" -ForegroundColor Cyan
Write-Host "Capture checkpoints: $CaptureDir"
Write-Host "SQLite database:    $DatabasePath"
Write-Host "CSV exports:        $ExportDir"
Write-Host "V13 knowledge DB:   $KnowledgeDB"
Write-Host "Listing audit:      $(Join-Path $CaptureDir 'catalog_audit.json')"
Write-Host "Detail audit:       $(Join-Path $CaptureDir 'details_audit.json')"

$codes = @($listingCode, $detailCode, $finalCaptureAuditCode, $syncCode, $databaseAuditCode, $independentCode, $knowledgeCode)
if ($codes | Where-Object { $_ -ne 0 }) {
    Write-Host "Collection remains partial or a step failed. Existing checkpoints and exports are retained; review the audit JSON before retrying." -ForegroundColor Yellow
    exit 2
}
Write-Host "Collection, database sync and completeness audits passed." -ForegroundColor Green
exit 0
