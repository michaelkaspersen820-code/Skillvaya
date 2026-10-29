$ErrorActionPreference = 'Stop'
$root = 'C:\Users\user\Documents\Codex\Skillvaya-Play-Prep-Latest-20261028'
$env:JAVA_HOME = 'C:\Program Files\Eclipse Adoptium\jdk-17.0.20.101-hotspot'
$env:ANDROID_HOME = Join-Path $env:LOCALAPPDATA 'Android\Sdk'
$env:ANDROID_SDK_ROOT = $env:ANDROID_HOME
$env:SKILLVAYA_KEYSTORE_PATH = Join-Path $env:LOCALAPPDATA 'Skillvaya\skillvaya-release.jks'
$pwPath = Join-Path $env:LOCALAPPDATA 'Skillvaya\release-signing-password.txt'
$pw = [IO.File]::ReadAllText($pwPath).Trim()
$env:SKILLVAYA_KEYSTORE_PASSWORD = $pw
$env:SKILLVAYA_KEY_PASSWORD = $pw
$env:SKILLVAYA_KEY_ALIAS = 'skillvaya-release'
$env:SKILLVAYA_PUBLIC_URL = 'https://skillvaya.onrender.com'
Set-Location (Join-Path $root 'android-native')
.\gradlew.bat bundleRelease assembleRelease --no-daemon
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
$release = Join-Path $root 'release'
Copy-Item 'app\build\outputs\bundle\release\app-release.aab' (Join-Path $release 'Skillvaya-7.1.5.1-versionCode54-production-candidate.aab') -Force
Copy-Item 'app\build\outputs\apk\release\app-release.apk' (Join-Path $release 'Skillvaya-7.1.5.1-versionCode54-production-candidate.apk') -Force
Write-Output 'BUILD_V54_OK'
Get-Item (Join-Path $release 'Skillvaya-7.1.5.1-versionCode54-production-candidate.aab'),(Join-Path $release 'Skillvaya-7.1.5.1-versionCode54-production-candidate.apk') | Select-Object FullName,Length,LastWriteTime