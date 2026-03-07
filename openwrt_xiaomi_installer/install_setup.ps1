#Requires -Version 5.1
<#
.SYNOPSIS
    OpenWRT Xiaomi Installer - Windows Setup & Launcher Script
.DESCRIPTION
    Elevates to Administrator, installs Python dependencies,
    configures Windows Firewall rules for FTP/Telnet,
    detects the correct network adapter, and launches the installer.
.PARAMETER ModelOverride
    Manually specify router model: auto, 4a_v1, 4a_v2, 4c
.PARAMETER BackupOnly
    Only backup partitions, skip firmware flash.
.PARAMETER NoBackup
    Skip partition backup.
.PARAMETER Force
    Skip confirmation prompts and re-download firmware.
.PARAMETER VerboseMode
    Enable DEBUG logging.
.PARAMETER Recovery
    Show recovery tools / launch MiWifi Repair Tool.
.PARAMETER GUI
    Launch the graphical (tkinter) installer instead of CLI.
#>

[CmdletBinding()]
param(
    [string]$ModelOverride = "auto",
    [switch]$BackupOnly,
    [switch]$NoBackup,
    [switch]$Force,
    [switch]$VerboseMode,
    [switch]$Recovery,
    [switch]$GUI,
    [string]$RouterIP = "192.168.31.1"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# ---- Colour helpers ----------------------------------------------------------
function Write-Header([string]$text) {
    Write-Host ""
    Write-Host "  $text" -ForegroundColor Cyan
    Write-Host ("  " + ("-" * $text.Length)) -ForegroundColor DarkCyan
}
function Write-OK([string]$text)   { Write-Host "  [OK] $text" -ForegroundColor Green  }
function Write-Warn([string]$text) { Write-Host "  [!!] $text" -ForegroundColor Yellow }
function Write-Err([string]$text)  { Write-Host "  [ERR] $text" -ForegroundColor Red   }
function Write-Info([string]$text) { Write-Host "  [*] $text"  -ForegroundColor White  }

# ---- ASCII Banner ------------------------------------------------------------
Clear-Host
Write-Host "  +----------------------------------------------------------+" -ForegroundColor Cyan
Write-Host "  |  OpenWRT Auto-Installer for Xiaomi Routers               |" -ForegroundColor Cyan
Write-Host "  |  Windows PowerShell Setup & Launcher                     |" -ForegroundColor Cyan
Write-Host "  +----------------------------------------------------------+" -ForegroundColor Cyan

# -----------------------------------------------------------------------------
# 1. Admin elevation
# -----------------------------------------------------------------------------
Write-Header "Checking Administrator Privileges"

$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator
)

if (-not $isAdmin) {
    Write-Warn "Not running as Administrator. Attempting elevation..."
    $scriptPath = $MyInvocation.MyCommand.Definition
    $argList    = "-NoProfile -ExecutionPolicy Bypass -File `"$scriptPath`""
    if ($ModelOverride -ne "auto") { $argList += " -ModelOverride $ModelOverride" }
    if ($BackupOnly)   { $argList += " -BackupOnly" }
    if ($NoBackup)     { $argList += " -NoBackup" }
    if ($Force)        { $argList += " -Force" }
    if ($VerboseMode)  { $argList += " -VerboseMode" }
    if ($Recovery)     { $argList += " -Recovery" }
    if ($GUI)          { $argList += " -GUI" }
    if ($RouterIP -ne "192.168.31.1") { $argList += " -RouterIP $RouterIP" }

    Start-Process powershell.exe -ArgumentList $argList -Verb RunAs -Wait
    exit
}
Write-OK "Running as Administrator."

# -----------------------------------------------------------------------------
# 2. Python detection
# -----------------------------------------------------------------------------
Write-Header "Checking Python Installation"

$python = $null
foreach ($cmd in @("python", "python3", "py")) {
    try {
        $ver = & $cmd --version 2>&1
        if ($ver -match "Python (\d+)\.(\d+)") {
            $major = [int]$Matches[1]; $minor = [int]$Matches[2]
            if ($major -ge 3 -and $minor -ge 10) {
                $python = $cmd
                Write-OK "Found: $ver (command: $cmd)"
                break
            } else {
                Write-Warn "Found $ver but Python 3.10+ is required."
            }
        }
    } catch { }
}

if ($null -eq $python) {
    Write-Err "Python 3.10+ is not installed or not in PATH."
    Write-Host ""
    Write-Host "  Download from: https://www.python.org/downloads/" -ForegroundColor Yellow
    Write-Host "  Ensure 'Add Python to PATH' is checked during install." -ForegroundColor Yellow
    Write-Host ""
    Read-Host "  Press Enter to exit"
    exit 1
}

# -----------------------------------------------------------------------------
# 3. Install / upgrade Python dependencies
# -----------------------------------------------------------------------------
Write-Header "Installing Python Dependencies"

$scriptDir        = Split-Path -Parent $MyInvocation.MyCommand.Definition
$requirementsFile = Join-Path $scriptDir "requirements.txt"

if (Test-Path $requirementsFile) {
    Write-Info "Running: pip install -r requirements.txt"
    & $python -m pip install --upgrade pip --quiet
    & $python -m pip install -r $requirementsFile --quiet
    if ($LASTEXITCODE -eq 0) {
        Write-OK "Dependencies installed successfully."
    } else {
        Write-Warn "Some dependencies may have failed. Check pip output above."
    }
} else {
    Write-Warn "requirements.txt not found at: $requirementsFile"
}

# -----------------------------------------------------------------------------
# 4. Windows Firewall rules
# -----------------------------------------------------------------------------
Write-Header "Configuring Windows Firewall"

$firewallRules = @(
    @{ Name="OpenWRT-Telnet-Out"; Port=23; Protocol="TCP"; Direction="Outbound"; Desc="Telnet to Xiaomi router" },
    @{ Name="OpenWRT-FTP-Out";    Port=21; Protocol="TCP"; Direction="Outbound"; Desc="FTP to Xiaomi router"    },
    @{ Name="OpenWRT-FTP-In";     Port=21; Protocol="TCP"; Direction="Inbound";  Desc="FTP from Xiaomi router"  }
)

foreach ($rule in $firewallRules) {
    $existing = Get-NetFirewallRule -DisplayName $rule.Name -ErrorAction SilentlyContinue
    if ($null -eq $existing) {
        try {
            $params = @{
                DisplayName = $rule.Name
                Description = $rule.Desc
                Direction   = $rule.Direction
                Protocol    = $rule.Protocol
                Action      = "Allow"
                Profile     = "Private,Domain"
                Enabled     = "True"
            }
            if ($rule.Direction -eq "Outbound") {
                $params.RemotePort = $rule.Port
            } else {
                $params.LocalPort  = $rule.Port
            }
            New-NetFirewallRule @params | Out-Null
            Write-OK "Created firewall rule: $($rule.Name)"
        } catch {
            Write-Warn "Could not create rule '$($rule.Name)': $_"
        }
    } else {
        Write-Info "Firewall rule already exists: $($rule.Name)"
    }
}

# -----------------------------------------------------------------------------
# 5. Network adapter detection
# -----------------------------------------------------------------------------
Write-Header "Detecting Network Adapter"

$routerSubnet   = "192.168.31."
$targetAdapter  = $null

$adapters = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue

foreach ($adapter in $adapters) {
    if ($adapter.IPAddress -like "$routerSubnet*") {
        $adapterInfo = Get-NetAdapter -InterfaceIndex $adapter.InterfaceIndex -ErrorAction SilentlyContinue
        Write-OK "Found adapter in router subnet: $($adapterInfo.Name) ($($adapter.IPAddress))"
        $targetAdapter = $adapterInfo
        break
    }
}

if ($null -eq $targetAdapter) {
    Write-Warn "No adapter found with IP in 192.168.31.0/24."
    Write-Warn "Make sure your LAN cable is connected to the router."
    Write-Info "Active IPv4 adapters:"
    Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.IPAddress -notlike "127.*" } | ForEach-Object {
        $ni = Get-NetAdapter -InterfaceIndex $_.InterfaceIndex -ErrorAction SilentlyContinue
        if ($ni) {
            Write-Host "    -> $($ni.Name): $($_.IPAddress)" -ForegroundColor DarkYellow
        }
    }
}

# -----------------------------------------------------------------------------
# 6. Router connectivity pre-check
# -----------------------------------------------------------------------------
Write-Header "Testing Router Connectivity"

$pingResult = Test-Connection -ComputerName $RouterIP -Count 1 -Quiet -ErrorAction SilentlyContinue
if ($pingResult) {
    Write-OK "Router at $RouterIP is reachable."
} else {
    Write-Warn "Cannot ping $RouterIP. Ensure the LAN cable is connected."
    Write-Warn "The installer will retry connectivity during execution."
}

# -----------------------------------------------------------------------------
# 7. Build Python command and launch
# -----------------------------------------------------------------------------
Write-Header "Launching Installer"

$installerScript = if ($GUI) {
    Join-Path $scriptDir "openwrt_gui.py"
} else {
    Join-Path $scriptDir "openwrt_installer.py"
}

if (-not (Test-Path $installerScript)) {
    Write-Err "Installer script not found: $installerScript"
    Read-Host "Press Enter to exit"
    exit 1
}

$pyArgs = @($installerScript)
if (-not $GUI) {
    $pyArgs += @("--model", $ModelOverride)
    $pyArgs += @("--ip",    $RouterIP)
    if ($BackupOnly)  { $pyArgs += "--backup-only" }
    if ($NoBackup)    { $pyArgs += "--no-backup" }
    if ($Force)       { $pyArgs += "--force" }
    if ($VerboseMode) { $pyArgs += "--verbose" }
    if ($Recovery)    { $pyArgs += "--recovery" }
}

Write-Info "Command: $python $($pyArgs -join ' ')"
Write-Host ""

Set-Location $scriptDir
& $python @pyArgs
$exitCode = $LASTEXITCODE

Write-Host ""
if ($exitCode -eq 0) {
    Write-OK "Installer finished successfully."
} else {
    Write-Err "Installer exited with code $exitCode. Check the log file for details."
}
Read-Host "`n  Press Enter to close"
exit $exitCode
