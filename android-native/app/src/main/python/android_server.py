import os
import threading
import app as skillvaya_app

def start_server(root, db_path):
    skillvaya_app.ROOT = root
    skillvaya_app.DB = db_path
    skillvaya_app.HOST = "127.0.0.1"
    skillvaya_app.PORT = 8878
    os.environ.pop("PORT", None)
    threading.Thread(target=skillvaya_app.main, name="SkillvayaHTTPServer", daemon=True).start()
    return True
