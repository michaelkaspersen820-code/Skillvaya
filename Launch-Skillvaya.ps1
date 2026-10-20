$ErrorActionPreference = 'Stop'
$root = 'C:\Users\user\Documents\Codex\Skillvaya'
$url = 'http://127.0.0.1:8877/'
# Prefer a standalone Chromium app window, not the default browser (which was Firefox).
$browserCandidates = @(
  "$env:ProgramFiles\Google\Chrome\Application\chrome.exe",
  "$env:ProgramFiles(x86)\Google\Chrome\Application\chrome.exe",
  "$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe",
  "$env:ProgramFiles(x86)\Microsoft\Edge\Application\msedge.exe",
  "$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe"
)
$browser = $browserCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $browser) {
  Add-Type -AssemblyName PresentationFramework
  [System.Windows.MessageBox]::Show('Skillvaya needs Google Chrome or Microsoft Edge installed to open in its own app window.','Skillvaya') | Out-Null
  exit 1
}
$healthy = $false
try { $r = Invoke-WebRequest -UseBasicParsing -Uri ($url + 'api/categories') -TimeoutSec 2; $healthy = ($r.StatusCode -eq 200) } catch {}
if (-not $healthy) {
  Start-Process -FilePath 'pythonw.exe' -ArgumentList ('"' + (Join-Path $root 'run_local.py') + '"') -WorkingDirectory $root -WindowStyle Hidden
  for ($i = 0; $i -lt 30; $i++) {
    Start-Sleep -Milliseconds 400
    try { $r = Invoke-WebRequest -UseBasicParsing -Uri ($url + 'api/categories') -TimeoutSec 2; if ($r.StatusCode -eq 200) { $healthy = $true; break } } catch {}
  }
}
if (-not $healthy) {
  Add-Type -AssemblyName PresentationFramework
  [System.Windows.MessageBox]::Show('Skillvaya could not start. Check that Python is installed and try again.','Skillvaya') | Out-Null
  exit 1
}
$profile = Join-Path $env:LOCALAPPDATA 'Skillvaya\AppWindowProfile'
Start-Process -FilePath $browser -ArgumentList @('--app=' + $url, '--user-data-dir=' + $profile, '--no-first-run')
