import os, sys, tempfile
sys.path.insert(0, r'C:\Users\user\Documents\Codex\Skillvaya')
import app
old_db = app.DB
old = {k: os.environ.get(k) for k in ('PORT','SKILLVAYA_OWNER_EMAIL','SKILLVAYA_OWNER_PASSWORD')}
try:
    with tempfile.TemporaryDirectory() as td:
        app.DB = os.path.join(td, 'test.sqlite3')
        os.environ['PORT'] = '10000'
        os.environ['SKILLVAYA_OWNER_EMAIL'] = 'owner-test@example.com'
        os.environ['SKILLVAYA_OWNER_PASSWORD'] = 'test-strong-password-1234'
        app.init()
        with app.conn() as c:
            row = c.execute('SELECT * FROM users WHERE email=?', ('owner-test@example.com',)).fetchone()
            assert row and row['role'] == 'admin'
            assert app.verify_password(row['password_hash'], 'test-strong-password-1234')
            assert not app.verify_password(row['password_hash'], 'wrong-password')
        print('PASS owner bootstraps as admin; password is hashed; correct password verifies; wrong password rejected')
finally:
    app.DB = old_db
    for k, v in old.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
