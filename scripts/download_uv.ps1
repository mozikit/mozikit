param(
    [string]$ManifestPath = "tools/bundled_uv.json",
    [string]$OutputPath = "build/bundled_uv/uv.exe"
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path -LiteralPath $ManifestPath)) {
    throw "Bundled UV manifest not found: $ManifestPath"
}

$manifest = Get-Content -LiteralPath $ManifestPath -Raw | ConvertFrom-Json
foreach ($property in @("version", "os", "architecture", "platform", "url", "sha256", "archive", "executable")) {
    if ([string]::IsNullOrWhiteSpace([string]$manifest.$property)) {
        throw "Bundled UV manifest is missing '$property'."
    }
}

$expectedSha256 = ([string]$manifest.sha256).ToLowerInvariant()
$tempRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("mozikit-uv-" + [guid]::NewGuid().ToString("N"))
$archivePath = Join-Path $tempRoot ([string]$manifest.archive)
$extractPath = Join-Path $tempRoot "extracted"
$resolvedOutput = [System.IO.Path]::GetFullPath($OutputPath)

try {
    New-Item -ItemType Directory -Force -Path $tempRoot | Out-Null
    Write-Host "Downloading pinned UV $($manifest.version) ($($manifest.os)-$($manifest.architecture)) from $($manifest.url)"
    Invoke-WebRequest -Uri ([string]$manifest.url) -OutFile $archivePath

    $actualSha256 = (Get-FileHash -LiteralPath $archivePath -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actualSha256 -ne $expectedSha256) {
        throw "Bundled UV SHA256 mismatch. Expected $expectedSha256, got $actualSha256"
    }
    Write-Host "Verified archive SHA256: $actualSha256"

    Expand-Archive -LiteralPath $archivePath -DestinationPath $extractPath -Force
    $uv = Get-ChildItem -LiteralPath $extractPath -Recurse -File -Filter ([string]$manifest.executable) |
        Select-Object -First 1
    if ($null -eq $uv) {
        throw "Bundled UV executable '$($manifest.executable)' was not found in the archive."
    }

    $outputDirectory = Split-Path -Parent $resolvedOutput
    New-Item -ItemType Directory -Force -Path $outputDirectory | Out-Null
    Copy-Item -LiteralPath $uv.FullName -Destination $resolvedOutput -Force

    $versionOutput = & $resolvedOutput --version 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "Bundled UV failed its smoke test: $versionOutput"
    }
    Write-Host "Bundled UV ready: $resolvedOutput ($versionOutput)"
}
finally {
    if (Test-Path -LiteralPath $tempRoot) {
        Remove-Item -LiteralPath $tempRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
}
