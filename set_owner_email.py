import sqlite3
p=r"C:\Users\user\Documents\Codex\Skillvaya\skillvaya.sqlite3"
c=sqlite3.connect(p)
c.execute("INSERT INTO settings(key,value) VALUES('owner_email','skillvaya@gmail.com') ON CONFLICT(key) DO UPDATE SET value=excluded.value",())
c.commit()
print("OWNER_EMAIL",c.execute("SELECT value FROM settings WHERE key='owner_email'").fetchone()[0])
c.close()
