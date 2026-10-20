from pathlib import Path
p=Path("verify_payfast_checkout.py"); s=p.read_text(); s=s.replace('assert status==201,(status,signup)','assert status==200,(status,signup)'); p.write_text(s)
