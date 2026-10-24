from pathlib import Path
import re, shutil, datetime
root=Path(__file__).resolve().parent
app=root/'app.py'
template=root/'owner_app_redesign.html'
source=app.read_text(encoding='utf-8')
html=template.read_text(encoding='utf-8')
pattern=r'OWNER_APP_HTML = r""".*?"""\nOWNER_HTML = r"""'
replacement='OWNER_APP_HTML = r"""'+html+'"""\nOWNER_HTML = r"""'
updated,n=re.subn(pattern,lambda m:replacement,source,count=1,flags=re.S)
if n!=1:
    raise SystemExit(f'Expected exactly one OWNER_APP_HTML block, replaced {n}; no changes made.')
backup=app.with_name('app.py.before_full_owner_console_'+datetime.datetime.now().strftime('%Y%m%d_%H%M%S')+'.bak')
shutil.copy2(app,backup)
app.write_text(updated,encoding='utf-8',newline='')
print('Updated only OWNER_APP_HTML. Backup:',backup.name)
