param(
    [Parameter(Mandatory = $true)]
    [string[]]$Path
)

$ErrorActionPreference = "Stop"

$certificateBase64 = $env:MOZIKIT_SIGNING_CERTIFICATE_BASE64
$certificatePassword = $env:MOZIKIT_SIGNING_CERTIFICATE_PASSWORD

if ([string]::IsNullOrWhiteSpace($certificateBase64) -or [string]::IsNullOrWhiteSpace($certificatePassword)) {
    Write-Warning "Authenticode signing is not configured; leaving unsigned build artifacts."
    exit 0
}

$signTool = Get-Command signtool.exe -ErrorAction SilentlyContinue
if ($null -eq $signTool) {
    throw "Signing secrets are configured but signtool.exe is not available on the runner."
}

$tempPfx = Join-Path ([System.IO.Path]::GetTempPath()) ("mozikit-signing-" + [guid]::NewGuid().ToString("N") + ".pfx")
try {
    [System.IO.File]::WriteAllBytes($tempPfx, [Convert]::FromBase64String($certificateBase64))
    foreach ($artifact in $Path) {
        if (-not (Test-Path -LiteralPath $artifact)) {
            throw "Cannot sign missing artifact: $artifact"
        }
        Write-Host "Signing $artifact"
        & $signTool.Source sign /fd SHA256 /f $tempPfx /p $certificatePassword /tr http://timestamp.digicert.com /td SHA256 $artifact
        if ($LASTEXITCODE -ne 0) {
            throw "signtool failed for $artifact with exit code $LASTEXITCODE"
        }
        & $signTool.Source verify /pa /all $artifact
        if ($LASTEXITCODE -ne 0) {
            throw "signtool verification failed for $artifact with exit code $LASTEXITCODE"
        }
    }
}
finally {
    if (Test-Path -LiteralPath $tempPfx) {
        Remove-Item -LiteralPath $tempPfx -Force -ErrorAction SilentlyContinue
    }
}
