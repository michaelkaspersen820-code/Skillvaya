$ErrorActionPreference = 'Stop'
$root = 'C:\Users\user\Documents\Codex\Skillvaya'
Set-Location $root
$py = 'C:\Users\user\AppData\Local\Programs\Python\Python312\python.exe'
Copy-Item 'app.py' 'android-native\app\src\main\python\app.py' -Force
Copy-Item 'website.html' 'android-native\app\src\main\assets\website.html' -Force
Copy-Item 'sv-logo.jpeg' 'android-native\app\src\main\assets\sv-logo.jpeg' -Force
Copy-Item 'icon-192.png' 'android-native\app\src\main\assets\icon-192.png' -Force
Copy-Item 'icon-512.png' 'android-native\app\src\main\assets\icon-512.png' -Force
Copy-Item 'icon-192.png' 'android-native\app\src\main\res\drawable\skillvaya_icon.png' -Force
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
.\gradlew.bat assembleRelease
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Copy-Item 'app\build\outputs\apk\release\app-release.apk' (Join-Path $root 'downloads\Skillvaya.apk') -Force
Write-Output 'APK_BUILD_OK'
Get-Item (Join-Path $root 'downloads\Skillvaya.apk') | Select-Object FullName,Length,LastWriteTime
