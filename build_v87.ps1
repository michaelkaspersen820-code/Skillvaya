$ErrorActionPreference='Stop'
$root='C:\Users\user\Documents\Codex\Skillvaya-kai-20261102'
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
if($code -ne 0){throw "Gradle release build failed: $code"}
$out=Join-Path $root 'release'
New-Item -ItemType Directory -Force $out | Out-Null
$apk=Join-Path $out 'Skillvaya-7.2.0.2-v87.apk'
Copy-Item 'app\build\outputs\apk\release\app-release.apk' $apk -Force
Copy-Item 'app\build\outputs\bundle\release\app-release.aab' (Join-Path $out 'Skillvaya-7.2.0.2-v87.aab') -Force
# Website download: a phone-only (arm64) copy under GitHub's 100 MB file limit.
$tmp=Join-Path $out 'v84-arm64-unsigned.apk'
Copy-Item $apk $tmp -Force
Add-Type -AssemblyName System.IO.Compression, System.IO.Compression.FileSystem
$z=[IO.Compression.ZipFile]::Open($tmp,'Update')
$drop=@($z.Entries | Where-Object { $_.FullName -like 'lib/*' -and $_.FullName -notlike 'lib/arm64-v8a/*' } | ForEach-Object { $_.FullName })
foreach($n in $drop){ $z.GetEntry($n).Delete() }
foreach($n in @($z.Entries | Where-Object { $_.FullName -like 'META-INF/*.SF' -or $_.FullName -like 'META-INF/*.RSA' -or $_.FullName -like 'META-INF/*.EC' -or $_.FullName -eq 'META-INF/MANIFEST.MF' } | ForEach-Object { $_.FullName })){ $z.GetEntry($n).Delete() }
$z.Dispose()
$bt=Get-ChildItem (Join-Path $env:ANDROID_HOME 'build-tools') | Sort-Object Name -Descending | Select-Object -First 1
$aligned=Join-Path $out 'v84-arm64-aligned.apk'
& (Join-Path $bt.FullName 'zipalign.exe') -p -f 4 $tmp $aligned
if($LASTEXITCODE -ne 0){throw 'zipalign failed'}
$web=Join-Path $out 'Skillvaya-7.2.0.2-v87-arm64.apk'
& (Join-Path $bt.FullName 'apksigner.bat') sign --ks $env:SKILLVAYA_KEYSTORE_PATH --ks-key-alias skillvaya-release --ks-pass "env:SKILLVAYA_KEYSTORE_PASSWORD" --key-pass "env:SKILLVAYA_KEY_PASSWORD" --out $web $aligned
if($LASTEXITCODE -ne 0){throw 'apksigner failed'}
& (Join-Path $bt.FullName 'apksigner.bat') verify $web
if($LASTEXITCODE -ne 0){throw 'apksigner verify failed'}
Remove-Item $tmp,$aligned -Force
$pw=$null
Remove-Item Env:SKILLVAYA_KEYSTORE_PASSWORD,Env:SKILLVAYA_KEY_PASSWORD -ErrorAction SilentlyContinue
Get-Item $apk,(Join-Path $out 'Skillvaya-7.2.0.2-v87.aab'),$web | Select-Object Name,Length,LastWriteTime | Format-Table -AutoSize
Write-Output 'v87_RELEASE_ARTIFACTS_BUILT'



