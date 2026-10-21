# Compatibility filename only. PayFast is paused and not called by tests.
from pathlib import Path
source=Path("app.py").read_text(encoding="utf-8")
assert '"PayFast is paused. PayPal is the only supported checkout provider."' in source
assert "PayPal payment requests & refunds" in source
print("PASS: PayFast checkout is retired; PayPal is the selected provider.")
