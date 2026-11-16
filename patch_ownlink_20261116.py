"""Wires ownlink.py (Michael's own PC connection) into app.py. Run once."""
import io, sys
P = 'app.py'
s = io.open(P, encoding='utf-8', newline='').read()
if 'import ownlink as OWN' in s:
    sys.exit('already wired')
def once(old, new):
    global s
    if s.count(old) != 1:
        sys.exit('expected one match: ' + old[:60] + ' (found %d)' % s.count(old))
    s = s.replace(old, new)
once('import kaspersen_ai as KAI\n', 'import kaspersen_ai as KAI\nimport ownlink as OWN\n')
once('    KAI.bind(globals())\n', '    KAI.bind(globals())\n    OWN.bind(KAI.A, KAI._verify)\n')
once('    def do_GET(self):\n        path=urlparse(self.path).path\n',
     '    def do_GET(self):\n        path=urlparse(self.path).path\n        if path.startswith("/mcp/"):\n            return OWN.handle_get(self,path)\n')
once('            d=self.body()\n            if path.startswith("/api/fc/") or path.startswith("/api/phone/"):\n',
     '            d=self.body()\n            if path.startswith("/mcp/"):\n                return OWN.handle_mcp(self,path,d)\n'
     '            if path.startswith("/api/own/"):\n                return OWN.handle_agent(self,path,d)\n'
     '            if path.startswith("/api/fc/") or path.startswith("/api/phone/"):\n')
io.open(P, 'w', encoding='utf-8', newline='').write(s)
print('wired')
