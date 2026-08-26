param(
    [switch]$Draft,
    [switch]$SkipBuild,
    [switch]$SkipTests,
    [switch]$SkipPush,
    [switch]$SkipSdkInstall
)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
Push-Location $repoRoot
try {
    if (-not (Get-Command gh -ErrorAction SilentlyContinue)) {
        throw 'GitHub CLI is not installed. Run: winget install --id GitHub.cli'
    }
    & gh auth status
    if ($LASTEXITCODE -ne 0) { throw 'GitHub CLI is not logged in. Run: gh auth login' }

    $version = (& python -c "import app_version; print(app_version.__version__)").Trim()
    $tag = "v$version"
    if (-not $version) { throw 'Unable to read application version' }

    & git diff --quiet --exit-code
    if ($LASTEXITCODE -ne 0) { throw 'Commit tracked changes before publishing a release' }
    & git diff --cached --quiet --exit-code
    if ($LASTEXITCODE -ne 0) { throw 'Commit staged changes before publishing a release' }

    if (-not $SkipTests) {
        & python -m unittest discover -s tests -v
        if ($LASTEXITCODE -ne 0) { throw "Tests failed ($LASTEXITCODE)" }
    }
    if (-not $SkipBuild) {
        $signingLoader = Join-Path $HOME '.han-nocm-release\load-signing.ps1'
        if (-not $env:HAN_NOCM_KEYSTORE -and (Test-Path -LiteralPath $signingLoader)) {
            . $signingLoader
        }
        $continuityKey = Join-Path $HOME '.android\debug.keystore'
        if (-not $env:HAN_NOCM_KEYSTORE -and (Test-Path -LiteralPath $continuityKey)) {
            $env:HAN_NOCM_KEYSTORE = $continuityKey
            $env:HAN_NOCM_STORE_PASSWORD = 'android'
            $env:HAN_NOCM_KEY_ALIAS = 'androiddebugkey'
            $env:HAN_NOCM_KEY_PASSWORD = 'android'
            Write-Warning 'Using the signing key from previously distributed APKs. Back up ~/.android/debug.keystore securely.'
        }
        & powershell -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'build_all.ps1') `
            -ReleaseAndroid -SkipSdkInstall:$SkipSdkInstall
        if ($LASTEXITCODE -ne 0) { throw "Release build failed ($LASTEXITCODE)" }
    }

    $windowsSource = Join-Path $repoRoot "dist\汉转NOCM-$version.exe"
    $windows = Join-Path $repoRoot "dist\HanToNocm-$version.exe"
    Copy-Item -LiteralPath $windowsSource -Destination $windows -Force
    $android = Join-Path $repoRoot "dist\android\HanToNocm-$version-release.apk"
    $metadata = Join-Path $repoRoot "dist\release-$version"
    & python (Join-Path $PSScriptRoot 'release_metadata.py') `
        --windows $windows --android $android --output $metadata
    if ($LASTEXITCODE -ne 0) { throw 'Failed to generate release metadata' }

    & git rev-parse --verify --quiet "refs/tags/$tag" | Out-Null
    if ($LASTEXITCODE -ne 0) {
        & git tag -a $tag -m "汉转NOCM $version"
        if ($LASTEXITCODE -ne 0) { throw 'Failed to create release tag' }
    }
    if (-not $SkipPush) {
        & git push origin HEAD
        if ($LASTEXITCODE -ne 0) { throw 'Failed to push current branch' }
        & git push origin $tag
        if ($LASTEXITCODE -ne 0) { throw 'Failed to push release tag' }
    }

    $arguments = @(
        'release', 'create', $tag,
        $windows, $android,
        (Join-Path $metadata 'update.json'),
        (Join-Path $metadata 'SHA256SUMS.txt'),
        '--verify-tag', '--title', "汉转NOCM $version",
        '--notes-file', (Join-Path $metadata 'release-notes.md')
    )
    if ($Draft) { $arguments += '--draft' }
    & gh @arguments
    if ($LASTEXITCODE -ne 0) { throw 'GitHub Release creation failed' }
    Write-Host "Published $tag"
} finally {
    Pop-Location
}
