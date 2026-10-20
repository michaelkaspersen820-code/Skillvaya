$p='C:\Users\user\Documents\Codex\Skillvaya\finish_owner_email_ui.py'
$src=@'
from pathlib import Path
import re
p=Path(r"C:\Users\user\Documents\Codex\Skillvaya\app.py")
s=p.read_text(encoding="utf-8")
# Owner page header branding; use the exact user-supplied image.
s=s.replace('<h1 style="margin:0">Skillvaya - Owner Control</h1>', '<div class="owner-brand"><img src="/sv-logo.jpeg" alt="SV Skillvaya logo"><div><h1 style="margin:0">Skillvaya - Owner Control</h1><div class="tiny">Owner workspace</div></div></div>')
s=re.sub(r'<div style="margin-top:8px"><a style="color:#fff" href="mailto:skillvaya@gmail\.com">skillvaya@gmail\.com</a>.*?</div></div></header>', '<div style="margin-top:8px">Platform email: <span id="ownerEmailLabel">skillvaya@gmail.com</span></div></div></div></header>', s, count=1)
# Owner email settings must remain within the app, not launch Gmail.
s=re.sub(r'<p><a href="mailto:skillvaya@gmail\.com">Compose a message in your email app</a>.*?</p><p class="muted">', '<p><button type="button" class="secondary" onclick="load(\\'compose\\')">Compose inside Skillvaya</button> <button type="button" class="secondary" onclick="load(\\'inbox\\')">Open Skillvaya inbox</button></p><p class="muted">', s, count=1)
# Remove Gmail inbox from footer while keeping support address.
s=re.sub(r' · <a href="https://mail\.google\.com/mail/u/0/#inbox" target="_blank" rel="noopener">Email inbox</a>', ' · Manage email in Owner Control', s, count=1)
p.write_text(s,encoding="utf-8")
print("owner logo:", 'class="owner-brand"><img src="/sv-logo.jpeg"' in s)
print("owner settings gmail links:", "Open Gmail inbox" in s)
print("external gmail URLs remaining:",s.count("mail.google.com"))
'@
[IO.File]::WriteAllText($p,$src,[Text.UTF8Encoding]::new($false))
python $p
if($LASTEXITCODE -ne 0){throw 'UI finalization failed'}
python -m py_compile 'C:\Users\user\Documents\Codex\Skillvaya\app.py'
if($LASTEXITCODE -ne 0){throw 'Syntax check failed'}
Write-Output 'Syntax check passed.'
