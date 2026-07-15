param(
    [Parameter(Mandatory = $true)]
    [string]$Tag,

    [Parameter(Mandatory = $true)]
    [string]$Repository,

    [Parameter(Mandatory = $true)]
    [string]$MsiPath
)

$ErrorActionPreference = "Stop"

if (-not $Tag.StartsWith("v")) {
    throw "Tag must start with 'v' (example: v0.1.0). Got: $Tag"
}

if (-not (Test-Path $MsiPath)) {
    throw "MSI not found: $MsiPath"
}

$pkgId = "Mozikit.Mozikit"
$version = $Tag.TrimStart("v")
$manifestDir = Join-Path "winget-manifests/manifests/l/Mozikit/Mozikit" $version
$msiUrl = "https://github.com/$Repository/releases/download/$Tag/mozikit-$Tag-x64.msi"
$sha256 = (Get-FileHash -Path $MsiPath -Algorithm SHA256).Hash

New-Item -ItemType Directory -Force -Path $manifestDir | Out-Null

$versionManifest = @"
PackageIdentifier: $pkgId
PackageVersion: $version
DefaultLocale: en-US
ManifestType: version
ManifestVersion: 1.6.0
"@

$installerManifest = @"
PackageIdentifier: $pkgId
PackageVersion: $version
Installers:
  - Architecture: x64
    InstallerType: wix
    Scope: machine
    InstallerUrl: $msiUrl
    InstallerSha256: $sha256
    InstallerSwitches:
      Silent: /quiet /norestart
      SilentWithProgress: /passive /norestart
      Custom: /norestart
ManifestType: installer
ManifestVersion: 1.6.0
"@

$localeManifest = @"
PackageIdentifier: $pkgId
PackageVersion: $version
PackageLocale: en-US
Publisher: Mozikit
PublisherUrl: https://github.com/mozikit
PackageName: Mozikit
PackageUrl: https://github.com/$Repository
License: Apache-2.0
LicenseUrl: https://github.com/$Repository/blob/main/LICENSE
ShortDescription: Visual workflow manager built with PySide6.
Description: Mozikit is a visual workflow editor and runner with node-based editing, environment management, and reusable workflow components.
Tags:
  - workflow
  - automation
  - pyside6
ManifestType: defaultLocale
ManifestVersion: 1.6.0
"@

Set-Content -Path (Join-Path $manifestDir "$pkgId.yaml") -Value $versionManifest -NoNewline
Set-Content -Path (Join-Path $manifestDir "$pkgId.installer.yaml") -Value $installerManifest -NoNewline
Set-Content -Path (Join-Path $manifestDir "$pkgId.locale.en-US.yaml") -Value $localeManifest -NoNewline

Write-Host "Generated manifests at $manifestDir"
Write-Host "MSI SHA256: $sha256"
