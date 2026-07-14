<#
.SYNOPSIS
    Install DHN-Pi as a Windows service that auto-starts with the OS.

.DESCRIPTION
    This script:
    1. Creates a Python virtual environment
    2. Installs dependencies
    3. Downloads NSSM (Non-Sucking Service Manager)
    4. Registers dhn-pi as a Windows service
#>

$ServiceName = "DHN-Pi"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$VenvPath = Join-Path $ProjectRoot "venv"
$PythonExe = Join-Path $VenvPath "Scripts\python.exe"
$DhnPiExe = Join-Path $VenvPath "Scripts\dhn-pi.exe"
$NssmPath = Join-Path $VenvPath "nssm.exe"
$NssmUrl = "https://nssm.cc/ci/nssm-2.24-101-g897c7ad.zip"
$LogDir = Join-Path $ProjectRoot "logs"

function Write-Step {
    param([string]$Message)
    Write-Host ">>> $Message" -ForegroundColor Cyan
}

# ---------------------------------------------------------------
# 1. Check Python
# ---------------------------------------------------------------
Write-Step "Checking Python installation..."
$py = Get-Command python -ErrorAction SilentlyContinue
if (-not $py) {
    Write-Error "Python not found. Install Python 3.11+ from https://python.org"
    exit 1
}

$pyVer = & python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
if ([version]$pyVer -lt [version]"3.11") {
    Write-Error "Python 3.11+ required, found $pyVer"
    exit 1
}

# ---------------------------------------------------------------
# 2. Create virtual environment
# ---------------------------------------------------------------
Write-Step "Creating virtual environment..."
if (Test-Path $VenvPath) {
    Write-Step "Removing existing venv..."
    Remove-Item -Recurse -Force $VenvPath
}
& python -m venv $VenvPath
if (-not (Test-Path $PythonExe)) {
    Write-Error "Failed to create virtual environment"
    exit 1
}

# ---------------------------------------------------------------
# 3. Install Python dependencies
# ---------------------------------------------------------------
Write-Step "Installing Python dependencies..."
& $PythonExe -m pip install --upgrade pip
& $PythonExe -m pip install -r (Join-Path $ProjectRoot "requirements.txt")
if ($LASTEXITCODE -ne 0) {
    Write-Error "pip install failed"
    exit 1
}

# Install the package itself (registers the `dhn-pi` CLI)
& $PythonExe -m pip install -e $ProjectRoot

# ---------------------------------------------------------------
# 4. Download NSSM
# ---------------------------------------------------------------
Write-Step "Downloading NSSM..."
if (-not (Test-Path $NssmPath)) {
    $zipPath = Join-Path $env:TEMP "nssm.zip"
    Invoke-WebRequest -Uri $NssmUrl -OutFile $zipPath -UseBasicParsing
    Expand-Archive -Path $zipPath -DestinationPath $env:TEMP -Force
    $nssmExe = Get-ChildItem -Path $env:TEMP -Recurse -Filter "nssm.exe" | Select-Object -First 1
    if ($nssmExe) {
        Copy-Item $nssmExe.FullName $NssmPath
    }
    Remove-Item $zipPath -Force
}

if (-not (Test-Path $NssmPath)) {
    Write-Error "Failed to download NSSM"
    exit 1
}

# ---------------------------------------------------------------
# 5. Create log directory
# ---------------------------------------------------------------
if (-not (Test-Path $LogDir)) {
    New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
}

# ---------------------------------------------------------------
# 6. Install / update service
# ---------------------------------------------------------------
$existing = & $NssmPath status $ServiceName 2>$null

if ($LASTEXITCODE -eq 0) {
    Write-Step "Stopping existing service..."
    & $NssmPath stop $ServiceName
    Start-Sleep -Seconds 2
    & $NssmPath remove $ServiceName confirm
}

Write-Step "Installing DHN-Pi Windows service..."
& $NssmPath install $ServiceName $DhnPiExe
& $NssmPath set $ServiceName AppDirectory $ProjectRoot
& $NssmPath set $ServiceName AppStdout (Join-Path $LogDir "stdout.log")
& $NssmPath set $ServiceName AppStderr (Join-Path $LogDir "stderr.log")
& $NssmPath set $ServiceName AppRotateFiles 1
& $NssmPath set $ServiceName AppRotateSeconds 86400
& $NssmPath set $ServiceName AppRotateBytes 10485760
& $NssmPath set $ServiceName Start SERVICE_AUTO_START
& $NssmPath set $ServiceName ObjectName LocalSystem

Write-Step "Starting service..."
& $NssmPath start $ServiceName

Write-Step "========================================"
Write-Step "DHN-Pi service installed successfully!"
Write-Step "Service name: $ServiceName"
Write-Step "Manage with:  $NssmPath (start|stop|restart|status) $ServiceName"
Write-Step "Logs:         $LogDir"
Write-Step "========================================"
