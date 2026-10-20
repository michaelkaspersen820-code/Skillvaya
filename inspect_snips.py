from pathlib import Path
s=Path('app.py').read_text(encoding='utf-8')
for k in ['async function choosePlan','Payment requests</h3>','async function verifyPayment','if path=="/api/admin/refunds"']:
 i=s.find(k); print('\n---',k,i,'---\n',s[i:i+1100] if i>=0 else 'NOT FOUND')
