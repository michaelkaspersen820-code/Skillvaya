from pathlib import Path
p=Path("verify_payfast_checkout.py"); s=p.read_text(); s=s.replace("os.unlink(db)\nprint(","print("); p.write_text(s)
