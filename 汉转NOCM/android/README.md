# Android build

The Android app reuses the repository's `web/` frontend and Python editing
core. Gradle copies the required Python modules and the two phonetic datasets
into generated build directories. Scheme JSON files are deliberately not
bundled, so a fresh installation starts without a default scheme.

Requirements:

- JDK 17 or newer
- Android SDK platform 35 and build-tools 35.0.0
- Gradle 8.9

From the repository root, run:

```powershell
powershell -ExecutionPolicy Bypass -File tools/build_android.ps1
```

The debug APK is copied to `dist/android/HanToPBOC-0.12.13-debug.apk`.

To build the Windows EXE and Android APK in one release pass, run:

```powershell
powershell -ExecutionPolicy Bypass -File tools/build_all.ps1 -SkipSdkInstall
```

## Signed release APK

Official updates must always use the same signing key. Set the four variables
shown in `tools/release-signing.example.ps1`, then build with:

```powershell
powershell -ExecutionPolicy Bypass -File tools/build_android.ps1 -Release -SkipSdkInstall
```

Never commit the keystore or its passwords. Losing the key prevents installed
copies from accepting future APK updates.

Existing Android copies were distributed with the local Android debug signing
identity. To preserve upgrade compatibility, the publish script automatically
uses `~/.android/debug.keystore` when no explicit release identity is set.
Back up that exact file securely: replacing it would force users to uninstall
the app before installing a future version.

After installing GitHub CLI and running `gh auth login`, a complete release can
be built, tagged and uploaded with:

```powershell
powershell -ExecutionPolicy Bypass -File tools/publish_release.ps1 -SkipSdkInstall
```
