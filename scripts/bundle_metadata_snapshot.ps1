# Copy bundled EUSFA Salesforce DX metadata into bundled_metadata/ for Docker builds.
# Copies only metadata XML directories used by SfdxMetadataLoader (no Apex, LWC, static resources).

param(
    [string]$SourcePath = $env:EUSFA_SFDX_REPO_PATH,
    [string]$TargetPath = (Join-Path (Join-Path $PSScriptRoot "..") "bundled_metadata"),
    [switch]$SkipAudit
)

$ErrorActionPreference = "Stop"

$MetadataSubdirs = @(
    "globalValueSets",
    "standardValueSets",
    "objects",
    "customMetadata"
)

function Write-Info([string]$Message) { Write-Host "[bundle] $Message" -ForegroundColor Cyan }
function Write-Warn([string]$Message) { Write-Host "[bundle] $Message" -ForegroundColor Yellow }

if (-not $SourcePath -or -not (Test-Path -LiteralPath $SourcePath)) {
    $defaultPath = Join-Path (Join-Path $env:USERPROFILE ".cursor") "EUSFA SF\EUROPE_SFA"
    if (Test-Path -LiteralPath $defaultPath) {
        $SourcePath = $defaultPath
        Write-Warn "Using default source path: $SourcePath"
    } else {
        throw "EUSFA source repo not found. Set EUSFA_SFDX_REPO_PATH or clone to $defaultPath"
    }
}

$SourcePath = (Resolve-Path -LiteralPath $SourcePath).Path
$TargetPath = [System.IO.Path]::GetFullPath($TargetPath)
$sourceDefault = Join-Path $SourcePath "force-app\main\default"

Write-Info "Source: $SourcePath"
Write-Info "Target: $TargetPath"

if (-not (Test-Path -LiteralPath (Join-Path $SourcePath "sfdx-project.json"))) {
    throw "Invalid SFDX repo - missing sfdx-project.json"
}
if (-not (Test-Path -LiteralPath $sourceDefault)) {
    throw "Invalid SFDX repo - missing force-app\main\default"
}

$stagingPath = "$TargetPath.__staging__"
if (Test-Path -LiteralPath $stagingPath) {
    Remove-Item -LiteralPath $stagingPath -Recurse -Force -ErrorAction SilentlyContinue
}
New-Item -ItemType Directory -Path (Join-Path $stagingPath "force-app\main\default") -Force | Out-Null

Copy-Item -LiteralPath (Join-Path $SourcePath "sfdx-project.json") `
    -Destination (Join-Path $stagingPath "sfdx-project.json") -Force

foreach ($subdir in $MetadataSubdirs) {
    $from = Join-Path $sourceDefault $subdir
    if (Test-Path -LiteralPath $from) {
        $to = Join-Path $stagingPath "force-app\main\default\$subdir"
        Write-Info "Copying force-app/main/default/$subdir ..."
        Copy-Item -LiteralPath $from -Destination $to -Recurse -Force
    } else {
        Write-Warn "Skipping missing metadata folder: $subdir"
    }
}

$commitHash = $null
$commitDate = $null
$branch = $null
    if (Test-Path -LiteralPath (Join-Path $SourcePath ".git")) {
        $commitHash = (& git -C $SourcePath rev-parse HEAD 2>$null)
        $commitDate = (& git -C $SourcePath log -1 --format=%cI 2>$null)
        $branch = (& git -C $SourcePath rev-parse --abbrev-ref HEAD 2>$null)
    }

$manifest = @{
    source_repo = "EUSFA_SFDX_REPO (local clone — path not stored in manifest)"
    bundled_at_utc = (Get-Date).ToUniversalTime().ToString("o")
    commit_hash = $commitHash
    commit_date = $commitDate
    branch = $branch
    contents = @(
        "sfdx-project.json",
        "force-app/main/default/globalValueSets",
        "force-app/main/default/standardValueSets",
        "force-app/main/default/objects",
        "force-app/main/default/customMetadata"
    )
    notes = "Read-only validation metadata only. No Apex, LWC, git history, or secrets."
}
$manifestPath = Join-Path $stagingPath "SNAPSHOT_MANIFEST.json"
$manifest | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $manifestPath -Encoding UTF8

Write-Info "Wrote $manifestPath"

if (-not $SkipAudit) {
    $auditScript = Join-Path $PSScriptRoot "audit_bundled_metadata.py"
    Write-Info "Running security audit..."
    python $auditScript --bundle-dir $stagingPath
    if ($LASTEXITCODE -ne 0) {
        throw "Security audit failed. Fix findings before building the container."
    }
}

if (Test-Path -LiteralPath $TargetPath) {
    Write-Info "Replacing bundled_metadata..."
    Remove-Item -LiteralPath $TargetPath -Recurse -Force -ErrorAction SilentlyContinue
}
Move-Item -LiteralPath $stagingPath -Destination $TargetPath

Write-Info "Bundle complete."
