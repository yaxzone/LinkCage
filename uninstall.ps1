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
    LinkCage - Windows Uninstaller
.DESCRIPTION
    Removes the native messaging host registration from Chrome.
#>

$ErrorActionPreference = "Stop"
$hostName = "com.linkcage.host"

$regPath = "HKCU:\Software\Google\Chrome\NativeMessagingHosts\$hostName"
if (Test-Path $regPath) {
    Remove-Item -Path $regPath -Force
    Write-Host "Registry key removed (Chrome): $regPath" -ForegroundColor Green
} else {
    Write-Host "Registry key not found (Chrome, already removed)" -ForegroundColor Yellow
}

$edgeRegPath = "HKCU:\Software\Microsoft\Edge\NativeMessagingHosts\$hostName"
if (Test-Path $edgeRegPath) {
    Remove-Item -Path $edgeRegPath -Force
    Write-Host "Registry key removed (Edge): $edgeRegPath" -ForegroundColor Green
} else {
    Write-Host "Registry key not found (Edge, already removed)" -ForegroundColor Yellow
}

$ffRegPath = "HKCU:\Software\Mozilla\NativeMessagingHosts\$hostName"
if (Test-Path $ffRegPath) {
    Remove-Item -Path $ffRegPath -Force
    Write-Host "Registry key removed (Firefox): $ffRegPath" -ForegroundColor Green
} else {
    Write-Host "Registry key not found (Firefox, already removed)" -ForegroundColor Yellow
}

$manifestDir = Join-Path $env:LOCALAPPDATA "LinkCage"
$manifestPath = Join-Path $manifestDir "$hostName.json"
if (Test-Path $manifestPath) {
    Remove-Item -Path $manifestPath -Force
    Write-Host "Manifest removed: $manifestPath" -ForegroundColor Green
} else {
    Write-Host "Manifest not found (already removed)" -ForegroundColor Yellow
}

$ffManifestPath = Join-Path $manifestDir "$hostName.firefox.json"
if (Test-Path $ffManifestPath) {
    Remove-Item -Path $ffManifestPath -Force
    Write-Host "Firefox manifest removed: $ffManifestPath" -ForegroundColor Green
} else {
    Write-Host "Firefox manifest not found (already removed)" -ForegroundColor Yellow
}

if ((Test-Path $manifestDir) -and -not (Get-ChildItem $manifestDir)) {
    Remove-Item $manifestDir -Force
}

Write-Host ""
Write-Host "=== LinkCage - Uninstalled ===" -ForegroundColor Green
Write-Host "  Restart Chrome for changes to take effect." -ForegroundColor Yellow
Write-Host ""
