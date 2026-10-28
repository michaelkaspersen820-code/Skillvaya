$ErrorActionPreference = 'Stop'
$root = 'C:\Users\user\Documents\Codex\Skillvaya-Play-Prep-Latest-20261028'
$ksPath = Join-Path $env:LOCALAPPDATA 'Skillvaya\skillvaya-release.jks'
$pwPath = Join-Path $env:LOCALAPPDATA 'Skillvaya\release-signing-password.txt'
if (!(Test-Path $ksPath)) { throw 'Release keystore missing; refusing to create an unsigned bundle.' }
if (!(Test-Path $pwPath)) { throw 'Release signing password file missing; refusing to create an unsigned bundle.' }

# This is a staging candidate builder, not a production deploy/build command.
$stagingUrl = $env:SKILLVAYA_PLAY_STAGING_URL
if ([string]::IsNullOrWhiteSpace($stagingUrl)) { throw 'Set SKILLVAYA_PLAY_STAGING_URL to the verified HTTPS staging host before building.' }
try { $uri = [Uri]$stagingUrl } catch { throw 'SKILLVAYA_PLAY_STAGING_URL is not a valid URL.' }
if ($uri.Scheme -ne 'https' -or [string]::IsNullOrWhiteSpace($uri.Host)) { throw 'The Play staging URL must use HTTPS.' }
if ($uri.Host -ieq 'skillvaya.onrender.com') { throw 'Refusing to build the staging candidate against the live production website.' }
if ($env:SKILLVAYA_PLAY_STAGING_DATABASE_CONFIRMED -ne 'YES') { throw 'Confirm the staging service uses a separate non-production database before building or testing.' }
if ($env:SKILLVAYA_EXPECTED_DATABASE -ne 'skillvaya_deletion_staging_db') { throw 'Set SKILLVAYA_EXPECTED_DATABASE to the database name verified by the staging startup guard before building.' }

# A working host and deletion/privacy pages are release preconditions.
foreach ($path in @('/customer-app', '/privacy', '/account-deletion')) {
    try {
        $response = Invoke-WebRequest -Uri ($stagingUrl.TrimEnd('/') + $path) -Method Get -UseBasicParsing -TimeoutSec 30
        if ([int]$response.StatusCode -ne 200) { throw "HTTP $([int]$response.StatusCode)" }
    } catch {
        throw "Staging preflight failed for $path. Fix staging before building. Details: $($_.Exception.Message)"
    }
}

$env:JAVA_HOME = 'C:\Program Files\Eclipse Adoptium\jdk-17.0.20.101-hotspot'
$env:ANDROID_HOME = Join-Path $env:LOCALAPPDATA 'Android\Sdk'
$env:ANDROID_SDK_ROOT = $env:ANDROID_HOME
$env:SKILLVAYA_KEYSTORE_PATH = $ksPath
$pw = [IO.File]::ReadAllText($pwPath).Trim()
$env:SKILLVAYA_KEYSTORE_PASSWORD = $pw
$env:SKILLVAYA_KEY_PASSWORD = $pw
$env:SKILLVAYA_KEY_ALIAS = 'skillvaya-release'
$env:SKILLVAYA_PUBLIC_URL = $stagingUrl.TrimEnd('/')

Set-Location (Join-Path $root 'android-native')
Write-Output 'BUILDING SIGNED SKILLVAYA 1.3.3 STAGING AAB — NO PRODUCTION DEPLOY'
& .\gradlew.bat bundleRelease --no-daemon
if ($LASTEXITCODE -ne 0) { throw "Gradle bundleRelease failed with exit code $LASTEXITCODE" }
$bundle = Join-Path $root 'android-native\app\build\outputs\bundle\release\app-release.aab'
if (!(Test-Path $bundle)) { throw 'Gradle reported success but the AAB was not found.' }
$outDir = Join-Path $root 'release'
New-Item -ItemType Directory -Force -Path $outDir | Out-Null
$outFile = Join-Path $outDir 'Skillvaya-1.3.3-play-staging.aab'
Copy-Item $bundle $outFile -Force
Get-Item $outFile | Select-Object FullName,Length,LastWriteTime | Format-List
Write-Output 'STAGING_AAB_BUILD_OK'
