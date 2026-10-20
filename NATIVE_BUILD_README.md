# Skillvaya native packages

## Artifacts

- `downloads/Skillvaya.apk`: signed Android release APK.
- `downloads/Skillvaya.exe`: portable Windows executable. It bundles the Python runtime, Skillvaya service, website assets, and the Android APK download.
- The website selects the APK on Android and the EXE on Windows at `/downloads/Skillvaya.apk` and `/downloads/Skillvaya.exe`.

## Android rebuild

The Android project is in `android-native/`. It uses Android Gradle Plugin 8.7.3, Gradle 8.9, Java 17, and Chaquopy to package the Python standard-library backend into the APK.

The release APK is signed with the local Skillvaya release keystore. Keep the keystore and its password file under `%LOCALAPPDATA%\Skillvaya\`; they are deliberately outside the source repository and must be preserved for future signed updates. Do not publish either file.

PowerShell build commands (after setting the Java and Android SDK paths):

```powershell
$env:JAVA_HOME = 'C:\Program Files\Eclipse Adoptium\jdk-17.0.20.101-hotspot'
$env:ANDROID_HOME = Join-Path $env:LOCALAPPDATA 'Android\Sdk'
$env:ANDROID_SDK_ROOT = $env:ANDROID_HOME
$env:SKILLVAYA_KEYSTORE_PATH = Join-Path $env:LOCALAPPDATA 'Skillvaya\skillvaya-release.jks'
$pw = [IO.File]::ReadAllText((Join-Path $env:LOCALAPPDATA 'Skillvaya\release-signing-password.txt')).Trim()
$env:SKILLVAYA_KEYSTORE_PASSWORD = $pw
$env:SKILLVAYA_KEY_PASSWORD = $pw
$env:SKILLVAYA_KEY_ALIAS = 'skillvaya-release'
.gradlew.bat assembleRelease
```

## Windows rebuild

The portable EXE is built with PyInstaller. The package bundles `website.html`, icons, logo, and `downloads/Skillvaya.apk`.

```powershell
python -m PyInstaller --noconfirm --clean --onefile --windowed --name Skillvaya --icon skillvaya.ico --add-data 'website.html;.' --add-data 'icon-192.png;.' --add-data 'icon-512.png;.' --add-data 'sv-logo.jpeg;.' --add-data 'downloads\Skillvaya.apk;downloads' desktop_launcher.py
Copy-Item dist\Skillvaya.exe downloads\Skillvaya.exe -Force
```

## Current release scope

Both native packages run a local Skillvaya service and a device-local SQLite database. They are usable as standalone builds, but different users' devices do not share one marketplace yet. A shared online marketplace and live PayFast transactions require production hosting, a stable public HTTPS URL, the approved merchant credentials, and an end-to-end payment notification test. The EXE is not Authenticode-signed, so Windows may display its normal unknown-publisher warning.
