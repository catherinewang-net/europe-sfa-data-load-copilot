# Europe SFA Data Load Copilot - one-command launcher (Windows PowerShell)
# Usage: .\scripts\run_copilot.ps1
#        .\scripts\run_copilot.ps1 -Port 8502

param(
    [int]$Port = 8501
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot

function Write-Info([string]$Message) { Write-Host $Message -ForegroundColor Cyan }
function Write-Warn([string]$Message) { Write-Host $Message -ForegroundColor Yellow }
function Write-Ok([string]$Message) { Write-Host $Message -ForegroundColor Green }

Write-Info "Europe SFA Data Load Copilot"
Write-Info "Project: $ProjectRoot"

# Python 3.11+
$pythonCmd = Get-Command python -ErrorAction SilentlyContinue
if (-not $pythonCmd) {
    Write-Error "Python not found on PATH. Install Python 3.11+ from https://www.python.org/downloads/ and enable Add to PATH."
}
$versionText = & python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
$parts = $versionText.Split(".")
$major = [int]$parts[0]
$minor = [int]$parts[1]
if ($major -lt 3 -or ($major -eq 3 -and $minor -lt 11)) {
    Write-Error "Python 3.11+ is required (found $versionText)."
}

# Virtual environment
$venvPython = Join-Path $ProjectRoot "venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    Write-Info "Creating virtual environment..."
    & python -m venv (Join-Path $ProjectRoot "venv")
}

Write-Info "Installing dependencies..."
& $venvPython -m pip install --upgrade pip --quiet
& $venvPython -m pip install -r (Join-Path $ProjectRoot "requirements.txt") --quiet

# .env setup
$envFile = Join-Path $ProjectRoot ".env"
$envExample = Join-Path $ProjectRoot ".env.example"
if (-not (Test-Path $envFile)) {
    if (Test-Path $envExample) {
        Copy-Item $envExample $envFile
        Write-Warn "Created .env from .env.example - set EUSFA_SFDX_REPO_PATH before validating files."
    } else {
        Write-Warn ".env not found. Set EUSFA_SFDX_REPO_PATH or use the default metadata path."
    }
}

# Load .env into process environment for this session
if (Test-Path $envFile) {
    Get-Content $envFile | ForEach-Object {
        $line = $_.Trim()
        if ($line -and -not $line.StartsWith("#") -and $line -match '^\s*([^=]+)=(.*)$') {
            $name = $Matches[1].Trim()
            $value = $Matches[2].Trim().Trim('"').Trim("'")
            if ($value) {
                Set-Item -Path "env:$name" -Value $value
            }
        }
    }
}

$metadataPath = $env:EUSFA_SFDX_REPO_PATH
if (-not $metadataPath) {
    $metadataPath = Join-Path $env:USERPROFILE ".cursor\EUSFA SF\EUROPE_SFA"
}

if (-not (Test-Path $metadataPath)) {
    Write-Warn "EUSFA metadata not found at: $metadataPath"
    Write-Warn "Clone the EUSFA Salesforce DX repo and set EUSFA_SFDX_REPO_PATH in .env."
    Write-Warn "See docs/TEAM_SETUP.md for full instructions."
} elseif (-not (Test-Path (Join-Path $metadataPath "sfdx-project.json"))) {
    Write-Warn "Path exists but sfdx-project.json is missing: $metadataPath"
    Write-Warn "Point EUSFA_SFDX_REPO_PATH at the SFDX project root (EUROPE_SFA)."
} else {
    Write-Ok "Metadata path: $metadataPath"
}

$streamlitExe = Join-Path $ProjectRoot "venv\Scripts\streamlit.exe"
$appPy = Join-Path $ProjectRoot "app.py"

Write-Info "Starting Streamlit on http://localhost:$Port"
Write-Info "Press Ctrl+C to stop."
& $streamlitExe run $appPy --server.port $Port
