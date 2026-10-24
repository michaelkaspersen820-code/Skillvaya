"""Regression test: the hosted owner-control shell must not be public."""
import http.client, os, tempfile, threading
from http.server import ThreadingHTTPServer

os.environ.pop('DATABASE_URL', None)
os.environ.pop('PORT', None)
os.environ['SKILLVAYA_HOST'] = '127.0.0.2'
fd, db_path = tempfile.mkstemp(prefix='skillvaya_owner_gate_', suffix='.sqlite3')
os.close(fd)
os.remove(db_path)
os.environ['SKILLVAYA_DB_PATH'] = db_path
import app

server = ThreadingHTTPServer(('127.0.0.2', 0), app.Handler)
thread = threading.Thread(target=server.serve_forever, daemon=True)
thread.start()

def request(path):
    conn = http.client.HTTPConnection('127.0.0.2', server.server_port, timeout=5)
    conn.request('GET', path)
    res = conn.getresponse()
    data = res.read()
    result = (res.status, dict(res.getheaders()), data)
    conn.close()
    return result

try:
    app.init()
    status, headers, body = request('/owner-control')
    assert status == 302, (status, headers, body[:200])
    assert headers.get('Location') == '/owner-app', headers
    assert headers.get('Cache-Control') == 'no-store', headers
    assert b'PayPal payment requests' not in body, body[:200]
    status, headers, body = request('/owner-app')
    assert status == 200 and b'Skillvaya | Owner App' in body and b'Full Platform Control' in body, (status, body[:200])
    status, headers, body = request('/api/admin/owner-promotions')
    assert status == 401, (status, body[:200])
    status, headers, body = request('/api/admin/payments')
    assert status == 401, (status, body[:200])
    print('PASS anonymous /owner-control redirects to /owner-app; owner APIs remain 401 without an owner session')
finally:
    server.shutdown(); server.server_close(); thread.join(timeout=2)
    for suffix in ('', '-wal', '-shm'):
        try: os.remove(db_path + suffix)
        except OSError: pass
