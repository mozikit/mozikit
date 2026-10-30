param(
    [string]$Msi = "release/mozikit-v0.2.5-parity-x64.msi",
    [string]$Zip = "release/Mozikit-Windows-x64.zip"
)
$ErrorActionPreference = "Stop"
# This entry point is for a disposable CI VM; it never runs on a developer host.
if ($env:GITHUB_ACTIONS -ne "true" -or $env:RUNNER_OS -ne "Windows") {
    throw "Packaged installer acceptance requires a disposable Windows GitHub Actions runner."
}
$msiPath = (Resolve-Path $Msi).Path
$zipPath = (Resolve-Path $Zip).Path
$root = Join-Path $env:RUNNER_TEMP "mozikit-packaged-parity"
$installedRoot = Join-Path $root "installed MSI\Mozikit"
$portableParent = Join-Path $root "portable"
$evidence = Join-Path (Get-Location) "packaged-verification"
New-Item -ItemType Directory -Force -Path $root, $evidence | Out-Null
Expand-Archive -LiteralPath $zipPath -DestinationPath $portableParent -Force
$installLog = Join-Path $evidence "msi-install.log"
$uninstallLog = Join-Path $evidence "msi-uninstall.log"
$installed = $false
$verificationExit = 1
function FileEvidence([string]$Path) {
    @{path = (Resolve-Path $Path).Path; sha256 = (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()}
}
try {
    $installArgs = "/i `"$msiPath`" /qn /norestart INSTALLFOLDER=`"$installedRoot`" /L*v `"$installLog`""
    $installer = Start-Process -FilePath "msiexec.exe" -ArgumentList $installArgs -Wait -PassThru
    if ($installer.ExitCode -notin @(0,3010)) { throw "MSI install failed: $($installer.ExitCode)" }
    $installed = $true
    $packages = @{}
    foreach ($kind in @("msi","portable")) {
        $directory = if ($kind -eq "msi") { $installedRoot } else { Join-Path $portableParent "Mozikit" }
        $distribution = if ($kind -eq "msi") { $msiPath } else { $zipPath }
        $packages[$kind] = @{
            distribution = (FileEvidence $distribution)
            cli = (FileEvidence (Join-Path $directory "mozikit.exe"))
            desktop = (FileEvidence (Join-Path $directory "MozikitDesktop.exe"))
        }
    }
    $manifest = @{
        source_ref = (git rev-parse HEAD).Trim()
        operator = "GitHub Actions/$env:GITHUB_ACTOR"
        observed_at = (Get-Date).ToUniversalTime().ToString("o")
        disposable_windows_host = $true
        packages = $packages
        observations = @{}
    }
    $env:MOZIKIT_ACCEPTANCE_EXTERNAL_MANIFEST = Join-Path $evidence "external-manifest.json"
    $manifest | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $env:MOZIKIT_ACCEPTANCE_EXTERNAL_MANIFEST -Encoding utf8NoBOM
    & python -m pytest test/acceptance/test_desktop_distribution.py -q -m "not live and not manual" `
        --junitxml="$evidence/tests.xml" --acceptance-report="$evidence/acceptance.json"
    $verificationExit = $LASTEXITCODE
    if ($verificationExit -eq 0) {
        & python tools/check_acceptance.py "$evidence/acceptance.json"
        $verificationExit = $LASTEXITCODE
    }
} finally {
    if ($installed) {
        $uninstallArgs = "/x `"$msiPath`" /qn /norestart /L*v `"$uninstallLog`""
        $uninstaller = Start-Process -FilePath "msiexec.exe" -ArgumentList $uninstallArgs -Wait -PassThru
        if ($uninstaller.ExitCode -notin @(0,3010)) { throw "MSI cleanup failed: $($uninstaller.ExitCode)" }
    }
}
exit $verificationExit
