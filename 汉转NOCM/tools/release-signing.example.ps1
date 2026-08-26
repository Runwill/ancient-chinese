# Copy this file outside the repository, replace the values, and run it in the
# same PowerShell session before tools/publish_release.ps1.
$env:HAN_NOCM_KEYSTORE = 'C:\secure\han-to-nocm-release.jks'
$env:HAN_NOCM_STORE_PASSWORD = 'replace-me'
$env:HAN_NOCM_KEY_ALIAS = 'han-to-nocm'
$env:HAN_NOCM_KEY_PASSWORD = 'replace-me'
