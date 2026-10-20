$desktop = [Environment]::GetFolderPath('Desktop')
$shortcut = Join-Path $desktop 'Skillvaya Owner Control.lnk'
$w = New-Object -ComObject WScript.Shell
$s = $w.CreateShortcut($shortcut)
$s.TargetPath = 'powershell.exe'
$s.Arguments = '-NoProfile -ExecutionPolicy Bypass -File "C:\Users\user\Documents\Codex\Skillvaya\Launch-Owner-Control.ps1"'
$s.WorkingDirectory = 'C:\Users\user\Documents\Codex\Skillvaya'
$s.IconLocation = 'C:\Users\user\Documents\Codex\Skillvaya\skillvaya.ico'
$s.Description = 'Open Skillvaya Owner Control without customer sign-in'
$s.Save()
Write-Output "Created $shortcut"
