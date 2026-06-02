# Copyright 2026 Luis Yax
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

<#
.SYNOPSIS
    LinkCage - Windows Installer
.DESCRIPTION
    Registers the native messaging host for Chrome so the LinkCage
    extension can communicate with the launcher script.
.PARAMETER ExtensionId
    The Chrome extension ID (from chrome://extensions after loading unpacked)
.PARAMETER GeckoId
    The Firefox extension (gecko) ID. Defaults to linkcage@yaxzone.
#>
param(
    [string[]]$ExtensionId = @(),
    [string]$GeckoId = "linkcage@yaxzone"
)

# Published Web Store extension IDs. After the extension is approved, add each
# store-assigned ID here (Chrome Web Store + Edge Add-ons). Store-installed users
# then get native messaging without passing -ExtensionId; dev/unpacked installs
# still pass their own ID via -ExtensionId.
$PublishedExtensionIds = @(
    "namalaooippodkhbjpjnagbgpggcphld"  # Edge Add-ons (LinkCage)
    # "<chrome-web-store-id>"           # add after Chrome approval
)

$ErrorActionPreference = "Stop"

# --- Dependency checks ----------------------------------------------------
# LinkCage needs Docker (to run the sandboxed browser) and Python 3.10+
# (the background helper). Fail fast with a friendly message rather than
# registering the host and breaking silently at runtime.

$dockerUrl = "https://www.docker.com/products/docker-desktop/"
$pythonUrl = "https://www.python.org/downloads/"
$missing = $false

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Write-Host ""
    Write-Host "ERROR: Docker is not installed." -ForegroundColor Red
    Write-Host "       LinkCage needs Docker Desktop to run the sandboxed browser." -ForegroundColor Yellow
    Write-Host "       Download: $dockerUrl" -ForegroundColor Cyan
    $missing = $true
} else {
    $null = & docker info 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Host ""
        Write-Host "WARNING: Docker is installed but the daemon isn't responding." -ForegroundColor Yellow
        Write-Host "         Start Docker Desktop from the Start menu and give it a minute." -ForegroundColor Gray
        # Not fatal.
    }
}

$pythonCmd = $null
$pythonFoundButTooOld = $null
foreach ($candidate in @("python", "python3")) {
    if (Get-Command $candidate -ErrorAction SilentlyContinue) {
        $null = & $candidate -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' 2>&1
        if ($LASTEXITCODE -eq 0) {
            $pythonCmd = $candidate
            break
        }
        # Exists but isn't 3.10+ (or doesn't actually run — e.g., MS Store stub).
        # Record only if we can extract a real version from it.
        if (-not $pythonFoundButTooOld) {
            $v = & $candidate -c 'import sys; print(sys.version.split()[0])' 2>$null
            if ($LASTEXITCODE -eq 0 -and $v) {
                $pythonFoundButTooOld = "$candidate ($v)"
            }
        }
    }
}

if (-not $pythonCmd) {
    Write-Host ""
    if ($pythonFoundButTooOld) {
        Write-Host "ERROR: Python 3.10 or newer is required (found: $pythonFoundButTooOld)." -ForegroundColor Red
        Write-Host "       Download a newer version: $pythonUrl" -ForegroundColor Cyan
    } else {
        Write-Host "ERROR: Python is not installed." -ForegroundColor Red
        Write-Host "       LinkCage's background helper is written in Python (3.10 or newer)." -ForegroundColor Yellow
        Write-Host "       Download: $pythonUrl" -ForegroundColor Cyan
    }
    Write-Host "       (Windows: on the first installer screen, check 'Add Python to PATH'.)" -ForegroundColor Gray
    $missing = $true
}

if ($missing) {
    Write-Host ""
    Write-Host "Install the missing requirement(s) and run this script again." -ForegroundColor Red
    exit 1
}
# --- end dependency checks -------------------------------------------------

$hostName = "com.linkcage.host"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$hostDir = Join-Path $scriptDir "host"
$launcherBat = Join-Path $hostDir "launcher.bat"

$launcherBatFull = (Resolve-Path $launcherBat).Path -replace '/', '\'

# Combine dev/unpacked ID(s) with published Store IDs into one allow-list.
$allExtIds = @(@($ExtensionId) + $PublishedExtensionIds | Where-Object { $_ })
if ($allExtIds.Count -eq 0) {
    Write-Host "ERROR: No extension IDs configured." -ForegroundColor Red
    Write-Host "       Pass -ExtensionId <id> (your unpacked dev ID from chrome://extensions)," -ForegroundColor Yellow
    Write-Host "       or add a published Store ID to `$PublishedExtensionIds in this script." -ForegroundColor Yellow
    exit 1
}
$allowedOrigins = @($allExtIds | ForEach-Object { "chrome-extension://$_/" })

$manifest = @{
    name = $hostName
    description = "LinkCage - Opens links in a sandboxed Docker Chromium container"
    path = $launcherBatFull
    type = "stdio"
    allowed_origins = @($allowedOrigins)
}

$manifestDir = Join-Path $env:LOCALAPPDATA "LinkCage"
if (-not (Test-Path $manifestDir)) {
    New-Item -ItemType Directory -Path $manifestDir -Force | Out-Null
}
$manifestPath = Join-Path $manifestDir "$hostName.json"
$manifest | ConvertTo-Json -Depth 5 | Out-File -FilePath $manifestPath -Encoding utf8

$regPath = "HKCU:\Software\Google\Chrome\NativeMessagingHosts\$hostName"
if (-not (Test-Path $regPath)) {
    New-Item -Path $regPath -Force | Out-Null
}
Set-ItemProperty -Path $regPath -Name "(Default)" -Value $manifestPath

# Edge uses the same Chromium-format manifest, registered under its own key.
$edgeRegPath = "HKCU:\Software\Microsoft\Edge\NativeMessagingHosts\$hostName"
if (-not (Test-Path $edgeRegPath)) {
    New-Item -Path $edgeRegPath -Force | Out-Null
}
Set-ItemProperty -Path $edgeRegPath -Name "(Default)" -Value $manifestPath

# Firefox: same launcher, allowed_extensions instead of allowed_origins
$ffManifest = @{
    name = $hostName
    description = "LinkCage - Opens links in a sandboxed Docker Chromium container"
    path = $launcherBatFull
    type = "stdio"
    allowed_extensions = @($GeckoId)
}
$ffManifestPath = Join-Path $manifestDir "$hostName.firefox.json"
$ffManifest | ConvertTo-Json -Depth 5 | Out-File -FilePath $ffManifestPath -Encoding utf8

$ffRegPath = "HKCU:\Software\Mozilla\NativeMessagingHosts\$hostName"
if (-not (Test-Path $ffRegPath)) {
    New-Item -Path $ffRegPath -Force | Out-Null
}
Set-ItemProperty -Path $ffRegPath -Name "(Default)" -Value $ffManifestPath

Write-Host ""
Write-Host "=== LinkCage - Installed ===" -ForegroundColor Green
Write-Host "  Native host manifest: $manifestPath" -ForegroundColor Gray
Write-Host "  Registry key:         $regPath" -ForegroundColor Gray
Write-Host "  Edge registry key:    $edgeRegPath" -ForegroundColor Gray
Write-Host "  Extension IDs:        $($allExtIds -join ', ')" -ForegroundColor Gray
Write-Host "  Firefox manifest:     $ffManifestPath" -ForegroundColor Gray
Write-Host "  Firefox registry key: $ffRegPath" -ForegroundColor Gray
Write-Host "  Gecko ID:             $GeckoId" -ForegroundColor Gray
Write-Host ""
Write-Host "Next steps:" -ForegroundColor Yellow
Write-Host "  1. Restart Chrome if it's running"
Write-Host "  2. Right-click any link -> 'LinkCage: Open in Sandbox'"
Write-Host ""
