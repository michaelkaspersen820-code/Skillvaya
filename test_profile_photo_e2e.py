import base64, json, os, tempfile, threading, time, urllib.request
from pathlib import Path
import sys
sys.path.insert(0, r"C:\Users\user\Documents\Codex\Skillvaya")
import app

tmp = tempfile.TemporaryDirectory(prefix="skillvaya-photo-e2e-")
app.DB = str(Path(tmp.name) / "e2e.sqlite3")
app.HOST = "127.0.0.1"
app.PORT = 8879
app.init()
server = app.ThreadingHTTPServer((app.HOST, app.PORT), app.Handler)
threading.Thread(target=server.serve_forever, daemon=True).start()
base = "http://127.0.0.1:8879"

def request(path, payload=None, token=None):
    headers = {"Content-Type":"application/json"}
    if token: headers["Authorization"] = "Bearer " + token
    req = urllib.request.Request(base+path, data=None if payload is None else json.dumps(payload).encode(), headers=headers, method="GET" if payload is None else "POST")
    with urllib.request.urlopen(req, timeout=5) as resp:
        return resp.status, json.loads(resp.read().decode())

try:
    for _ in range(30):
        try:
            with urllib.request.urlopen(base+"/healthz", timeout=1): break
        except Exception: time.sleep(.1)
    status, page = 200, urllib.request.urlopen(base+"/").read().decode()
    assert 'id="profilePhotoFile"' in page
    assert 'id="profileCameraFile"' in page
    assert 'id="saveProfilePhotoButton"' in page
    assert "otherInput.value=''" in page
    print("UI: choose-photo, take-photo, upload-picture controls present; selected source is exclusive")
    status, created = request("/api/signup", {"name":"E2E Photo Tester","email":"e2e-photo-"+str(int(time.time()))+"@example.test","password":"SafeTestPass123!","role":"customer","accept_terms":True})
    token = created["token"]
    png = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jK6kAAAAASUVORK5CYII="
    status, saved = request("/api/account/profile", {"name":"E2E Photo Tester","phone":"","profile_photo":png}, token)
    assert status == 200 and saved["user"]["profile_photo"] == png
    status, current = request("/api/me", token=token)
    assert current["user"]["profile_photo"] == png
    with app.conn() as c:
        row = c.execute("SELECT profile_photo FROM users WHERE id=?", (created["user"]["id"],)).fetchone()
        assert row["profile_photo"] == png
    print("API E2E: account signup -> photo upload -> API response -> /api/me reload -> database persistence PASSED")
    print("RESULT: PASS")
finally:
    server.shutdown()
    server.server_close()
    tmp.cleanup()
