param(
    [switch]$Release,
    [switch]$SkipSdkInstall
)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$toolsRoot = Join-Path $repoRoot '.android-tools'
$sdkRoot = if ($env:ANDROID_SDK_ROOT) { $env:ANDROID_SDK_ROOT } elseif ($env:ANDROID_HOME) { $env:ANDROID_HOME } else { Join-Path $env:USERPROFILE '.android-sdk-han-nocm' }
$gradleVersion = '8.9'
$gradleHome = Join-Path $toolsRoot "gradle-$gradleVersion"
$commandToolsVersion = '11076708'

function Get-Archive([string]$Url, [string]$Destination) {
    if ((Test-Path -LiteralPath $Destination) -and
        (Get-Item -LiteralPath $Destination).Length -gt 0) {
        try {
            Add-Type -AssemblyName System.IO.Compression.FileSystem
            $archive = [System.IO.Compression.ZipFile]::OpenRead($Destination)
            $entryCount = $archive.Entries.Count
            $archive.Dispose()
            if ($entryCount -eq 0) { throw 'ZIP archive has no entries' }
            return
        } catch {
            Write-Host "Resuming incomplete archive $Destination"
        }
    }
    New-Item -ItemType Directory -Path (Split-Path -Parent $Destination) -Force | Out-Null
    Write-Host "Downloading $Url"
    & curl.exe --fail --location --retry 3 --retry-delay 2 --continue-at - `
        --output $Destination $Url
    if ($LASTEXITCODE -ne 0 -or (Get-Item -LiteralPath $Destination).Length -eq 0) {
        throw "Download failed: $Url"
    }
    $archive = [System.IO.Compression.ZipFile]::OpenRead($Destination)
    if ($archive.Entries.Count -eq 0) { throw "Downloaded ZIP archive has no entries: $Destination" }
    $archive.Dispose()
}

New-Item -ItemType Directory -Path $toolsRoot, $sdkRoot -Force | Out-Null

if (-not (Test-Path -LiteralPath (Join-Path $gradleHome 'bin\gradle.bat'))) {
    $gradleZip = Join-Path $toolsRoot "gradle-$gradleVersion-bin.zip"
    Get-Archive "https://repo.huaweicloud.com/gradle/gradle-$gradleVersion-bin.zip" $gradleZip
    $expectedGradleHash = 'D725D707BFABD4DFDC958C624003B3C80ACCC03F7037B5122C4B1D0EF15CECAB'
    $actualGradleHash = (Get-FileHash -LiteralPath $gradleZip -Algorithm SHA256).Hash
    if ($actualGradleHash -ne $expectedGradleHash) {
        throw "Gradle archive checksum mismatch: $actualGradleHash"
    }
    Expand-Archive -LiteralPath $gradleZip -DestinationPath $toolsRoot -Force
}

$sdkManager = Join-Path $sdkRoot 'cmdline-tools\latest\bin\sdkmanager.bat'
if (-not (Test-Path -LiteralPath $sdkManager)) {
    if ($SkipSdkInstall) {
        throw "Android SDK command-line tools not found at $sdkManager"
    }
    $commandToolsZip = Join-Path $toolsRoot "commandlinetools-win-$commandToolsVersion.zip"
    $unpackDir = Join-Path $toolsRoot 'commandlinetools-unpacked'
    Get-Archive "https://dl.google.com/android/repository/commandlinetools-win-${commandToolsVersion}_latest.zip" $commandToolsZip
    if (Test-Path -LiteralPath $unpackDir) { Remove-Item -LiteralPath $unpackDir -Recurse -Force }
    Expand-Archive -LiteralPath $commandToolsZip -DestinationPath $unpackDir -Force
    $latestDir = Join-Path $sdkRoot 'cmdline-tools\latest'
    New-Item -ItemType Directory -Path (Split-Path -Parent $latestDir) -Force | Out-Null
    if (Test-Path -LiteralPath $latestDir) { Remove-Item -LiteralPath $latestDir -Recurse -Force }
    Move-Item -LiteralPath (Join-Path $unpackDir 'cmdline-tools') -Destination $latestDir
}

$env:ANDROID_HOME = $sdkRoot
$env:ANDROID_SDK_ROOT = $sdkRoot
$java = Get-Command java -ErrorAction Stop
if (-not $env:JAVA_HOME) {
    $installedJdk = Get-ChildItem 'C:\Program Files\Java' -Directory -ErrorAction SilentlyContinue |
        Where-Object { Test-Path -LiteralPath (Join-Path $_.FullName 'bin\javac.exe') } |
        Sort-Object Name -Descending | Select-Object -First 1
    if (-not $installedJdk) { throw 'JAVA_HOME is not set and no JDK was found' }
    $env:JAVA_HOME = $installedJdk.FullName
}

if (-not $SkipSdkInstall) {
    $licenseDir = Join-Path $sdkRoot 'licenses'
    New-Item -ItemType Directory -Path $licenseDir -Force | Out-Null
    Set-Content -LiteralPath (Join-Path $licenseDir 'android-sdk-license') -Encoding ASCII -Value @(
        '24333f8a63b6825ea9c5514f83c2829b004d1fee',
        '8933bad161af4178b1185d1a37fbf41ea5269c55',
        'd56f5187479451eabf01fb78af6dfcb131a6481e'
    )
    Set-Content -LiteralPath (Join-Path $licenseDir 'android-sdk-preview-license') -Encoding ASCII -Value @(
        '84831b9409646a918e30573bab4c9c91346d8abd'
    )
    & $sdkManager --sdk_root=$sdkRoot 'platform-tools' 'platforms;android-35' 'build-tools;34.0.0' 'build-tools;35.0.0'
    if ($LASTEXITCODE -ne 0) { throw "Android SDK package installation failed ($LASTEXITCODE)" }
}

$sdkProperty = $sdkRoot.Replace('\', '/').Replace(':', '\:')
Set-Content -LiteralPath (Join-Path $repoRoot 'android\local.properties') -Value "sdk.dir=$sdkProperty" -Encoding ASCII

$variant = if ($Release) { 'Release' } else { 'Debug' }
$gradle = Join-Path $gradleHome 'bin\gradle.bat'
Push-Location (Join-Path $repoRoot 'android')
try {
    & $gradle "`:app`:assemble$variant" --stacktrace
    if ($LASTEXITCODE -ne 0) { throw "Gradle build failed ($LASTEXITCODE)" }
} finally {
    Pop-Location
}

$version = & python -c "import app_version; print(app_version.__version__)"
$variantLower = $variant.ToLowerInvariant()
$sourceApk = Join-Path $repoRoot "android\app\build\outputs\apk\$variantLower\app-$variantLower.apk"
$distDir = Join-Path $repoRoot 'dist\android'
$targetApk = Join-Path $distDir "HanToNocm-$version-$variantLower.apk"
New-Item -ItemType Directory -Path $distDir -Force | Out-Null
Copy-Item -LiteralPath $sourceApk -Destination $targetApk -Force
$hash = Get-FileHash -LiteralPath $targetApk -Algorithm SHA256
Write-Host "APK: $targetApk"
Write-Host "SHA256: $($hash.Hash)"
