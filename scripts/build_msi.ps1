param(
    [Parameter(Mandatory = $true)]
    [string]$Tag,

    [string]$SourceDir = "dist/Mozikit",
    [string]$OutputDir = "release"
)

$ErrorActionPreference = "Stop"

if (-not $Tag.StartsWith("v")) {
    throw "Tag must start with 'v' (example: v0.1.0). Got: $Tag"
}

if (-not (Test-Path $SourceDir)) {
    throw "Missing build output directory: $SourceDir"
}
$resolvedSourceDir = (Resolve-Path $SourceDir).Path

function Get-WixCommand {
    param([string]$Name)
    $cmd = Get-Command $Name -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    throw "Required WiX command '$Name' not found in PATH. Install WiX Toolset v3 (choco install wixtoolset)."
}

function Convert-ToWixVersion {
    param([string]$Version)
    $cleanVersion = $Version.TrimStart("v")
    $core = ($cleanVersion -split "-", 2)[0]
    $parts = $core.Split(".")
    $nums = @()
    foreach ($part in $parts) {
        if ($part -match "^\d+$") {
            $nums += [int]$part
        } else {
            $nums += 0
        }
    }
    while ($nums.Count -lt 3) { $nums += 0 }
    return "$($nums[0]).$($nums[1]).$($nums[2])"
}

$heat = Get-WixCommand -Name "heat.exe"
$candle = Get-WixCommand -Name "candle.exe"
$light = Get-WixCommand -Name "light.exe"

$projectRoot = Resolve-Path "."
$workDir = Join-Path $projectRoot "build/wix"
$objDir = Join-Path $workDir "obj"
$wxsOut = Join-Path $workDir "harvested.wxs"
$templateWxs = Join-Path $projectRoot "wix/main.wxs"
$mainWxsOut = Join-Path $workDir "main.wxs"
$productVersion = Convert-ToWixVersion -Version $Tag
$msiName = "mozikit-$Tag-x64.msi"

New-Item -ItemType Directory -Force -Path $workDir | Out-Null
New-Item -ItemType Directory -Force -Path $objDir | Out-Null
New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null

if (-not (Test-Path $templateWxs)) {
    throw "Missing WiX template: $templateWxs"
}

# Render a concrete .wxs to avoid preprocessor variable mismatches across environments.
$templateContent = Get-Content -Path $templateWxs -Raw
$renderedContent = $templateContent.Replace("__PRODUCT_VERSION__", $productVersion)
Set-Content -Path $mainWxsOut -Value $renderedContent -Encoding utf8

# Copy icon to WiX work directory so candle can resolve mozikit.ico
$iconSource = Join-Path $projectRoot "assets\mozikit.ico"
if (-not (Test-Path $iconSource)) {
    throw "Missing icon file: $iconSource"
}
Copy-Item -Path $iconSource -Destination (Join-Path $workDir "mozikit.ico") -Force

# Also copy icon to source directory so light.exe can find it during linking
Copy-Item -Path $iconSource -Destination (Join-Path $resolvedSourceDir "mozikit.ico") -Force

Write-Host "Harvesting files from $SourceDir"
& $heat dir $resolvedSourceDir `
    -nologo `
    -cg MozikitFiles `
    -dr INSTALLFOLDER `
    -gg `
    -scom `
    -sreg `
    -sfrag `
    -srd `
    -out $wxsOut
if ($LASTEXITCODE -ne 0) { throw "heat.exe failed with exit code $LASTEXITCODE" }

Write-Host "Compiling WiX sources (ProductVersion=$productVersion)"
& $candle `
    -nologo `
    -arch x64 `
    -out (Join-Path $objDir "") `
    $mainWxsOut `
    $wxsOut
if ($LASTEXITCODE -ne 0) { throw "candle.exe failed with exit code $LASTEXITCODE" }

$mainWixObj = Join-Path $objDir "main.wixobj"
$harvestedWixObj = Join-Path $objDir "harvested.wixobj"
if (-not (Test-Path $mainWixObj)) {
    throw "Expected WiX object missing: $mainWixObj"
}
if (-not (Test-Path $harvestedWixObj)) {
    throw "Expected WiX object missing: $harvestedWixObj"
}

$msiOut = Join-Path $OutputDir $msiName
Write-Host "Linking MSI -> $msiOut"
& $light `
    -nologo `
    -ext WixUIExtension `
    -ext WixUtilExtension `
    -b $resolvedSourceDir `
    -out $msiOut `
    $mainWixObj `
    $harvestedWixObj
if ($LASTEXITCODE -ne 0) { throw "light.exe failed with exit code $LASTEXITCODE" }
if (-not (Test-Path $msiOut)) { throw "MSI output not found: $msiOut" }

Write-Host "MSI build complete: $msiOut"
