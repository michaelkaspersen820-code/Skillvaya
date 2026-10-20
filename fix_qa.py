from pathlib import Path
p=Path("qa_one_go.py"); s=p.read_text()
s=s.replace('if path=="/": return body.decode("utf-8",errors="replace")','if path in ("/","/customer","/owner-control"): return body.decode("utf-8",errors="replace")')
s=s.replace('"PayFast payment requests &amp; refunds"','"PayFast payment requests"')
p.write_text(s)
