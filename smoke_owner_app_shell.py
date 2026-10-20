from http.server import ThreadingHTTPServer
from threading import Thread
from urllib.request import urlopen
import app
srv=ThreadingHTTPServer(('127.0.0.1',0),app.Handler)
Thread(target=srv.serve_forever,daemon=True).start()
base='http://127.0.0.1:'+str(srv.server_port)
try:
    tests=[
      ('/', 'Skillvaya Owner App'),
      ('/owner-app', 'Welcome to your Skillvaya Owner App'),
      ('/customer', 'Find the right people'),
      ('/owner-control', 'Owner Control'),
      ('/manifest.json', 'Skillvaya Owner App'),
    ]
    for path,needle in tests:
      with urlopen(base+path,timeout=3) as r:
        body=r.read().decode('utf-8')
        ok=r.status==200 and needle in body
        print(('PASS' if ok else 'FAIL'),path,'HTTP',r.status,'contains expected content:',needle in body)
        if not ok: raise SystemExit(1)
finally:
    srv.shutdown(); srv.server_close()
