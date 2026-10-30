$ErrorActionPreference='Stop'
$root='C:\Users\user\Documents\Codex\Skillvaya-bell-fix-20261030'
$env:JAVA_HOME='C:\Program Files\Eclipse Adoptium\jdk-17.0.20.101-hotspot'
$env:ANDROID_HOME=Join-Path $env:LOCALAPPDATA 'Android\Sdk'
$env:ANDROID_SDK_ROOT=$env:ANDROID_HOME
$env:SKILLVAYA_KEYSTORE_PATH=Join-Path $env:LOCALAPPDATA 'Skillvaya\skillvaya-release.jks'
$pwPath=Join-Path $env:LOCALAPPDATA 'Skillvaya\release-signing-password.txt'
if (!(Test-Path $env:SKILLVAYA_KEYSTORE_PATH) -or !(Test-Path $pwPath)) { throw 'Release signing inputs missing; no unsigned release will be created.' }
$pw=[IO.File]::ReadAllText($pwPath).Trim()
$env:SKILLVAYA_KEYSTORE_PASSWORD=$pw
$env:SKILLVAYA_KEY_PASSWORD=$pw
$env:SKILLVAYA_KEY_ALIAS='skillvaya-release'
$env:SKILLVAYA_PUBLIC_URL='https://skillvaya.onrender.com'
Set-Location (Join-Path $root 'android-native')
& .\gradlew.bat assembleRelease bundleRelease --no-daemon
$code=$LASTEXITCODE
$pw=$null
Remove-Item Env:SKILLVAYA_KEYSTORE_PASSWORD,Env:SKILLVAYA_KEY_PASSWORD -ErrorAction SilentlyContinue
if($code -ne 0){throw "Gradle release build failed: $code"}
$out=Join-Path $root 'release'
New-Item -ItemType Directory -Force $out | Out-Null
Copy-Item 'app\build\outputs\apk\release\app-release.apk' (Join-Path $out 'Skillvaya-7.1.7.1-v74.apk') -Force
Copy-Item 'app\build\outputs\bundle\release\app-release.aab' (Join-Path $out 'Skillvaya-7.1.7.1-v74.aab') -Force
Get-Item (Join-Path $out 'Skillvaya-7.1.7.1-v74.apk'),(Join-Path $out 'Skillvaya-7.1.7.1-v74.aab') | Select-Object Name,Length,LastWriteTime | Format-Table -AutoSize
Write-Output 'BOTH_SIGNED_RELEASE_ARTIFACTS_BUILT'