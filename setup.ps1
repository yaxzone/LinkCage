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
    LinkCage - Setup & Management (Windows)
.DESCRIPTION
    Manage your LinkCage installation.
    No flags        = Run full setup
    -start          = Start the sandbox container + open browser
    -stop           = Stop the container + close incognito window
    -status         = Show container and browser status
    -uninstall      = Full removal (container, host registration, config)
.PARAMETER start
    Start the sandbox container and open the browser
.PARAMETER stop
    Stop the sandbox container and close the incognito browser window
.PARAMETER status
    Show current status of container and browser
.PARAMETER uninstall
    Full uninstall: stop container, remove host registration, clean up
#>
param(
    [switch]$start,
    [switch]$stop,
    [switch]$status,
    [switch]$uninstall,
    [string]$GeckoId = "linkcage@yaxzone"
)

$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$hostName = "com.linkcage.host"
$configPath = Join-Path $scriptDir "config.json"

# ── Load config ──────────────────────────────────────────────────
function Get-LinkCageConfig {
    $defaults = @{
        containerName = "chromium-browser"
        composePath = Join-Path $scriptDir "docker"
        composeFile = "docker-compose.yml"
        localPort = 3443
        protocol = "https"
        chromiumProfileDir = ".chromium-profile"
    }
    try {
        $cfg = Get-Content $configPath -Raw | ConvertFrom-Json
        foreach ($key in $defaults.Keys) {
            if (-not ($cfg.PSObject.Properties.Name -contains $key) -or -not $cfg.$key) {
                $cfg | Add-Member -NotePropertyName $key -NotePropertyValue $defaults[$key] -Force
            }
        }
        return $cfg
    } catch {
        return [PSCustomObject]$defaults
    }
}

# ══════════════════════════════════════════════════════════════════
# ── STOP ─────────────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════
if ($stop) {
    $config = Get-LinkCageConfig
    $userDataDir = Join-Path $config.composePath $config.chromiumProfileDir

    # Close incognito Chrome window
    Write-Host "Closing sandbox browser window..." -ForegroundColor Cyan
    $chromeProcs = Get-CimInstance Win32_Process -Filter "Name='chrome.exe'" |
        Where-Object { $_.CommandLine -match [regex]::Escape($userDataDir) }
    if ($chromeProcs) {
        $chromeProcs | ForEach-Object {
            & taskkill /F /T /PID $_.ProcessId 2>$null | Out-Null
        }
        Write-Host "  Browser window closed." -ForegroundColor Green
    } else {
        Write-Host "  No sandbox browser window found." -ForegroundColor Gray
    }

    # Stop Docker container
    $running = docker ps --filter "name=$($config.containerName)" --format "{{.Names}}" 2>$null
    if ($running) {
        Write-Host "Stopping sandbox container..." -ForegroundColor Cyan
        $composeFile = Join-Path $config.composePath $config.composeFile
        docker compose -f $composeFile down
        Write-Host "  Container stopped." -ForegroundColor Green
    } else {
        Write-Host "  Container is not running." -ForegroundColor Gray
    }
    exit 0
}

# ══════════════════════════════════════════════════════════════════
# ── START ────────────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════
if ($start) {
    $config = Get-LinkCageConfig
    $composeFile = Join-Path $config.composePath $config.composeFile
    $userDataDir = Join-Path $config.composePath $config.chromiumProfileDir

    # Start container if not running
    $running = docker ps --filter "name=$($config.containerName)" --format "{{.Names}}" 2>$null
    if ($running) {
        Write-Host "Sandbox container is already running." -ForegroundColor Yellow
    } else {
        Write-Host "Starting sandbox container..." -ForegroundColor Green
        docker compose -f $composeFile up -d
    }

    # Open browser to container UI
    Write-Host "Opening sandbox browser..." -ForegroundColor Cyan
    $containerUrl = "$($config.protocol)://localhost:$($config.localPort)"
    Start-Process "chrome.exe" -ArgumentList "--incognito", "--user-data-dir=`"$userDataDir`"", $containerUrl
    Write-Host "  Done." -ForegroundColor Green
    exit 0
}

# ══════════════════════════════════════════════════════════════════
# ── STATUS ───────────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════
if ($status) {
    $config = Get-LinkCageConfig
    $userDataDir = Join-Path $config.composePath $config.chromiumProfileDir

    Write-Host ""
    Write-Host "  LinkCage Status" -ForegroundColor Cyan
    Write-Host "  ───────────────" -ForegroundColor Cyan

    # Container
    $running = docker ps --filter "name=$($config.containerName)" --format "{{.Names}}" 2>$null
    if ($running) {
        docker ps --filter "name=$($config.containerName)" --format "table {{.Names}}`t{{.Status}}`t{{.Ports}}"
    } else {
        Write-Host "  Container: Not running" -ForegroundColor Yellow
    }

    # Browser
    $chromeProcs = Get-CimInstance Win32_Process -Filter "Name='chrome.exe'" |
        Where-Object { $_.CommandLine -match [regex]::Escape($userDataDir) } |
        Select-Object -First 1
    if ($chromeProcs) {
        Write-Host "  Browser:   Running (PID: $($chromeProcs.ProcessId))" -ForegroundColor Green
    } else {
        Write-Host "  Browser:   Not running" -ForegroundColor Gray
    }

    # Host registration
    $regPath = "HKCU:\Software\Google\Chrome\NativeMessagingHosts\$hostName"
    if (Test-Path $regPath) {
        Write-Host "  Host:      Registered (Chrome)" -ForegroundColor Green
    } else {
        Write-Host "  Host:      Not registered (Chrome)" -ForegroundColor Yellow
    }
    $edgeRegPath = "HKCU:\Software\Microsoft\Edge\NativeMessagingHosts\$hostName"
    if (Test-Path $edgeRegPath) {
        Write-Host "  Host:      Registered (Edge)" -ForegroundColor Green
    } else {
        Write-Host "  Host:      Not registered (Edge)" -ForegroundColor Yellow
    }
    $ffRegPath = "HKCU:\Software\Mozilla\NativeMessagingHosts\$hostName"
    if (Test-Path $ffRegPath) {
        Write-Host "  Host:      Registered (Firefox)" -ForegroundColor Green
    } else {
        Write-Host "  Host:      Not registered (Firefox)" -ForegroundColor Yellow
    }
    Write-Host ""
    exit 0
}

# ══════════════════════════════════════════════════════════════════
# ── UNINSTALL ────────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════
if ($uninstall) {
    Write-Host ""
    Write-Host "  LinkCage - Uninstalling..." -ForegroundColor Yellow
    Write-Host ""

    $config = Get-LinkCageConfig
    $userDataDir = Join-Path $config.composePath $config.chromiumProfileDir

    # Stop browser
    $chromeProcs = Get-CimInstance Win32_Process -Filter "Name='chrome.exe'" |
        Where-Object { $_.CommandLine -match [regex]::Escape($userDataDir) }
    if ($chromeProcs) {
        $chromeProcs | ForEach-Object {
            & taskkill /F /T /PID $_.ProcessId 2>$null | Out-Null
        }
        Write-Host "  Browser window closed." -ForegroundColor Green
    }

    # Stop container
    $running = docker ps --filter "name=$($config.containerName)" --format "{{.Names}}" 2>$null
    if ($running) {
        $composeFile = Join-Path $config.composePath $config.composeFile
        docker compose -f $composeFile down
        Write-Host "  Container stopped." -ForegroundColor Green
    }

    # Remove registry keys (Chrome + Edge + Firefox)
    $regPath = "HKCU:\Software\Google\Chrome\NativeMessagingHosts\$hostName"
    if (Test-Path $regPath) {
        Remove-Item -Path $regPath -Force
        Write-Host "  Registry key removed (Chrome)." -ForegroundColor Green
    }
    $edgeRegPath = "HKCU:\Software\Microsoft\Edge\NativeMessagingHosts\$hostName"
    if (Test-Path $edgeRegPath) {
        Remove-Item -Path $edgeRegPath -Force
        Write-Host "  Registry key removed (Edge)." -ForegroundColor Green
    }
    $ffRegPath = "HKCU:\Software\Mozilla\NativeMessagingHosts\$hostName"
    if (Test-Path $ffRegPath) {
        Remove-Item -Path $ffRegPath -Force
        Write-Host "  Registry key removed (Firefox)." -ForegroundColor Green
    }

    # Remove manifests
    $manifestDir = Join-Path $env:LOCALAPPDATA "LinkCage"
    $manifestPath = Join-Path $manifestDir "$hostName.json"
    if (Test-Path $manifestPath) {
        Remove-Item -Path $manifestPath -Force
        Write-Host "  Host manifest removed." -ForegroundColor Green
    }
    $ffManifestPath = Join-Path $manifestDir "$hostName.firefox.json"
    if (Test-Path $ffManifestPath) {
        Remove-Item -Path $ffManifestPath -Force
        Write-Host "  Firefox host manifest removed." -ForegroundColor Green
    }
    if ((Test-Path $manifestDir) -and -not (Get-ChildItem $manifestDir)) {
        Remove-Item $manifestDir -Force
    }

    # Clean up chromium profile
    if (Test-Path $userDataDir) {
        Remove-Item -Path $userDataDir -Recurse -Force -ErrorAction SilentlyContinue
        Write-Host "  Browser profile cleaned." -ForegroundColor Green
    }

    # Remove LinkCage data directory (verdict cache, URLhaus feed, debug logs)
    $linkCageDataDir = Join-Path $env:LOCALAPPDATA "LinkCage"
    if (Test-Path $linkCageDataDir) {
        Remove-Item -Path $linkCageDataDir -Recurse -Force -ErrorAction SilentlyContinue
        Write-Host "  LinkCage data directory removed (verdict cache, URLhaus feed)." -ForegroundColor Green
    }

    # Remove project virtualenv
    $venvDir = Join-Path $scriptDir ".venv"
    if (Test-Path $venvDir) {
        Remove-Item -Path $venvDir -Recurse -Force -ErrorAction SilentlyContinue
        Write-Host "  Virtualenv removed." -ForegroundColor Green
    }

    Write-Host ""
    Write-Host "  ╔══════════════════════════════════════════╗" -ForegroundColor Green
    Write-Host "  ║       LinkCage - Uninstalled             ║" -ForegroundColor Green
    Write-Host "  ╚══════════════════════════════════════════╝" -ForegroundColor Green
    Write-Host ""
    Write-Host "  Remove the extension from chrome://extensions manually." -ForegroundColor White
    Write-Host "  To remove the Docker image: docker rmi luisyax/linkcage-sandbox:hardened" -ForegroundColor Gray
    Write-Host ""
    exit 0
}

# ══════════════════════════════════════════════════════════════════
# ── SETUP (default, no flags) ────────────────────────────────────
# ══════════════════════════════════════════════════════════════════

# ── Banner ──────────────────────────────────────────────────────
Write-Host ""
Write-Host "  ╔══════════════════════════════════════════╗" -ForegroundColor Cyan
Write-Host "  ║          LinkCage Setup v1.0.0           ║" -ForegroundColor Cyan
Write-Host "  ║    Don't click it. Cage it.              ║" -ForegroundColor Cyan
Write-Host "  ╚══════════════════════════════════════════╝" -ForegroundColor Cyan
Write-Host ""

# ── Step 1: Check prerequisites ─────────────────────────────────
Write-Host "[1/6] Checking prerequisites..." -ForegroundColor Yellow

# Docker
$dockerCheck = Get-Command docker -ErrorAction SilentlyContinue
if (-not $dockerCheck) {
    Write-Host "  ERROR: Docker is not installed or not on PATH." -ForegroundColor Red
    Write-Host "  Install Docker Desktop: https://www.docker.com/products/docker-desktop/" -ForegroundColor Red
    exit 1
}
$dockerRunning = docker info 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "  ERROR: Docker is not running. Start Docker Desktop first." -ForegroundColor Red
    exit 1
}
Write-Host "  Docker: OK" -ForegroundColor Green

# Python
$pythonCheck = Get-Command python -ErrorAction SilentlyContinue
if (-not $pythonCheck) {
    Write-Host "  ERROR: Python 3 is not installed or not on PATH." -ForegroundColor Red
    exit 1
}
Write-Host "  Python: OK" -ForegroundColor Green

# Isolated virtualenv — host Python runs here, never against system Python
$venvDir = Join-Path $scriptDir ".venv"
$venvPy = Join-Path $venvDir "Scripts\python.exe"
if (-not (Test-Path $venvPy)) {
    Write-Host "  Creating virtualenv at .venv ..." -ForegroundColor Cyan
    python -m venv "$venvDir"
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path $venvPy)) {
        Write-Host "  ERROR: Failed to create virtualenv." -ForegroundColor Red
        exit 1
    }
}
$reqFile = Join-Path $scriptDir "requirements.txt"
if (Test-Path $reqFile) {
    & $venvPy -m pip install --quiet --upgrade pip
    & $venvPy -m pip install --quiet -r $reqFile
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  ERROR: pip install failed." -ForegroundColor Red
        exit 1
    }
}
Write-Host "  Virtualenv: OK" -ForegroundColor Green

# Chrome
$chromeCheck = Get-Command chrome -ErrorAction SilentlyContinue
if (-not $chromeCheck) {
    $chromePath = "C:\Program Files\Google\Chrome\Application\chrome.exe"
    if (-not (Test-Path $chromePath)) {
        $chromePath = "C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"
    }
    if (-not (Test-Path $chromePath)) {
        Write-Host "  WARNING: Chrome not found in default location. You may need to load the extension manually." -ForegroundColor Yellow
    } else {
        Write-Host "  Chrome: OK" -ForegroundColor Green
    }
} else {
    $chromePath = "chrome"
    Write-Host "  Chrome: OK" -ForegroundColor Green
}

# ── Step 2: Pull the hardened Docker image ───────────────────────
Write-Host ""
Write-Host "[2/6] Checking Docker image..." -ForegroundColor Yellow
$imageExists = docker images luisyax/linkcage-sandbox:hardened --format "{{.ID}}" 2>$null
if ($imageExists) {
    Write-Host "  Image already present, skipping pull." -ForegroundColor Green
} else {
    Write-Host "  Pulling hardened Docker image..." -ForegroundColor Yellow
    docker pull luisyax/linkcage-sandbox:hardened
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  ERROR: Failed to pull image. No network or Docker Hub unreachable." -ForegroundColor Red
        Write-Host "  You can build locally instead: docker build -t luisyax/linkcage-sandbox:hardened docker/" -ForegroundColor Yellow
        exit 1
    }
    Write-Host "  Image pulled: OK" -ForegroundColor Green
}

# ── Step 3: Configure ───────────────────────────────────────────
Write-Host ""
Write-Host "[3/6] Configuring environment..." -ForegroundColor Yellow

$dockerDir = Join-Path $scriptDir "docker"
$config = Get-Content $configPath -Raw | ConvertFrom-Json

if (-not $config.composePath -or $config.composePath -eq "") {
    $config.composePath = $dockerDir
    $config | ConvertTo-Json -Depth 5 | Out-File -FilePath $configPath -Encoding utf8
    Write-Host "  composePath set to: $dockerDir" -ForegroundColor Gray
}
Write-Host "  Config: OK" -ForegroundColor Green

# ── Step 4: Load Chrome extension ────────────────────────────────
Write-Host ""
Write-Host "[4/6] Chrome extension setup..." -ForegroundColor Yellow
Write-Host ""
Write-Host "  Opening Chrome to the extensions page..." -ForegroundColor Cyan

$extensionDir = Join-Path $scriptDir "extension"

if ($chromePath -and (Test-Path $chromePath -ErrorAction SilentlyContinue)) {
    Start-Process $chromePath -ArgumentList "chrome://extensions"
} else {
    Start-Process "chrome.exe" -ArgumentList "chrome://extensions" -ErrorAction SilentlyContinue
}

Write-Host ""
Write-Host "  ┌────────────────────────────────────────────────────────────┐" -ForegroundColor White
Write-Host "  │  In Chrome:                                                │" -ForegroundColor White
Write-Host "  │                                                            │" -ForegroundColor White
Write-Host "  │  1. Enable 'Developer mode' (toggle, top right)           │" -ForegroundColor White
Write-Host "  │  2. Click 'Load unpacked'                                  │" -ForegroundColor White
Write-Host "  │  3. Select this folder:                                    │" -ForegroundColor White
Write-Host "  │     $extensionDir" -ForegroundColor Yellow -NoNewline
Write-Host "  │" -ForegroundColor White
Write-Host "  │  4. Copy the Extension ID shown on the card                │" -ForegroundColor White
Write-Host "  │                                                            │" -ForegroundColor White
Write-Host "  └────────────────────────────────────────────────────────────┘" -ForegroundColor White
Write-Host ""

$extensionId = Read-Host "  Paste your Extension ID here"
$extensionId = $extensionId.Trim()

if (-not $extensionId -or $extensionId.Length -lt 10) {
    Write-Host "  ERROR: Invalid Extension ID." -ForegroundColor Red
    exit 1
}
Write-Host "  Extension ID: $extensionId" -ForegroundColor Green

# ── Step 5: Register native messaging host ──────────────────────
Write-Host ""
Write-Host "[5/6] Registering native messaging host..." -ForegroundColor Yellow

$hostDir = Join-Path $scriptDir "host"
$launcherBat = Join-Path $hostDir "launcher.bat"
$launcherBatFull = (Resolve-Path $launcherBat).Path -replace '/', '\'

$manifest = @{
    name = $hostName
    description = "LinkCage - Opens links in a sandboxed Docker Chromium container"
    path = $launcherBatFull
    type = "stdio"
    allowed_origins = @("chrome-extension://$extensionId/")
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

Write-Host "  Manifest: $manifestPath" -ForegroundColor Gray
Write-Host "  Registry: $regPath" -ForegroundColor Gray
Write-Host "  Edge registry: $edgeRegPath" -ForegroundColor Gray
Write-Host "  Firefox manifest: $ffManifestPath" -ForegroundColor Gray
Write-Host "  Firefox registry: $ffRegPath" -ForegroundColor Gray
Write-Host "  Gecko ID: $GeckoId" -ForegroundColor Gray
Write-Host "  Host registered: OK" -ForegroundColor Green

# ── Step 6: Start the container ──────────────────────────────────
Write-Host ""
Write-Host "[6/6] Starting sandbox container..." -ForegroundColor Yellow

# Remove stale container if it exists but is stopped
$staleContainer = docker ps -a --filter "name=chromium-browser" --filter "status=exited" --format "{{.ID}}" 2>$null
if ($staleContainer) {
    Write-Host "  Removing stale container..." -ForegroundColor Gray
    docker rm chromium-browser 2>$null | Out-Null
}

$composeFile = Join-Path $config.composePath $config.composeFile
$running = docker ps --filter "name=chromium-browser" --format "{{.Names}}" 2>$null
if ($running) {
    Write-Host "  Container is already running." -ForegroundColor Green
} else {
    docker compose -f $composeFile up -d
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  WARNING: Container may not have started. Check Docker Desktop." -ForegroundColor Yellow
    } else {
        Write-Host "  Container started: OK" -ForegroundColor Green
    }
}

# ── Done ─────────────────────────────────────────────────────────
Write-Host ""
Write-Host "  ╔══════════════════════════════════════════╗" -ForegroundColor Green
Write-Host "  ║       LinkCage setup complete!           ║" -ForegroundColor Green
Write-Host "  ╚══════════════════════════════════════════╝" -ForegroundColor Green
Write-Host ""
Write-Host "  1. Restart Chrome" -ForegroundColor White
Write-Host "  2. Right-click any link -> 'LinkCage: Open in Sandbox'" -ForegroundColor White
Write-Host ""
Write-Host "  Management commands:" -ForegroundColor Gray
Write-Host "    setup.ps1 -start      Start the sandbox" -ForegroundColor Gray
Write-Host "    setup.ps1 -stop       Stop the sandbox" -ForegroundColor Gray
Write-Host "    setup.ps1 -status     Check status" -ForegroundColor Gray
Write-Host "    setup.ps1 -uninstall  Full removal" -ForegroundColor Gray
Write-Host ""
Write-Host "  Don't click it. Cage it." -ForegroundColor Cyan
Write-Host ""
