from pathlib import Path
p=Path(r'C:\Users\user\Documents\Codex\Skillvaya\app.py')
s=p.read_text(encoding='utf-8')
s=s.replace('Open payment records and refund controls. PayFast is not live-connected yet; real transactions remain disabled until integration and testing are complete.','Open payment records. Refund actions will be added with the PayFast integration; they are not available yet. PayFast is not live-connected, so real transactions remain disabled.',1)
old = """<iframe class="frame" src="/owner-control#payments" title="Skillvaya payment controls"></iframe>"""
new = """<iframe class="frame" src="/owner-control" title="Skillvaya payment controls"></iframe>"""
s=s.replace(old,new,1)
s=s.replace('<p class="muted">Gateway connection status:', '<p class="muted">Refund controls are not implemented yet. Gateway connection status:',1)
p.write_text(s,encoding='utf-8')
print('Payment wording corrected.')
