param([switch]$SkipSdkInstall, [switch]$ReleaseAndroid)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
Push-Location $repoRoot
try {
    & python build_exe.py
    if ($LASTEXITCODE -ne 0) { throw "Windows build failed ($LASTEXITCODE)" }

    $androidArguments = @(
        '-ExecutionPolicy', 'Bypass',
        '-File', (Join-Path $PSScriptRoot 'build_android.ps1')
    )
    if ($SkipSdkInstall) { $androidArguments += '-SkipSdkInstall' }
    if ($ReleaseAndroid) { $androidArguments += '-Release' }
    & powershell @androidArguments
    if ($LASTEXITCODE -ne 0) { throw "Android build failed ($LASTEXITCODE)" }

    $version = & python -c "import app_version; print(app_version.__version__)"
    $releaseDir = Join-Path $repoRoot "dist\release-$version-empty-schemes"
    New-Item -ItemType Directory -Path $releaseDir -Force | Out-Null
    $windowsCandidates = @(Get-ChildItem (Join-Path $repoRoot 'dist') `
        -Filter "*-$version.exe" -File)
    if ($windowsCandidates.Count -ne 1) {
        throw "Expected one Windows executable for version $version, found $($windowsCandidates.Count)"
    }
    $windowsExe = $windowsCandidates[0].FullName
    Copy-Item -LiteralPath $windowsExe -Destination $releaseDir -Force

    Write-Host "Windows release: $releaseDir"
    $androidVariant = if ($ReleaseAndroid) { 'release' } else { 'debug' }
    Write-Host "Android release: $(Join-Path $repoRoot "dist\android\HanToNocm-$version-$androidVariant.apk")"
} finally {
    Pop-Location
}
