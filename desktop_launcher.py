import os, sys, time, threading, subprocess, urllib.request
from pathlib import Path

def main():
    bundle_root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    appdata = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))) / "Skillvaya"
    appdata.mkdir(parents=True, exist_ok=True)
    # Release builds can point to the shared hosted marketplace. Local/offline mode
    # remains available only when no HTTPS deployment URL has been configured.
    remote_url = os.environ.get("SKILLVAYA_PUBLIC_URL", "").strip()
    config_path = bundle_root / "deployment.json"
    if not remote_url and config_path.exists():
        try:
            import json
            remote_url = str(json.loads(config_path.read_text(encoding="utf-8")).get("public_url", "")).strip()
        except Exception:
            remote_url = ""
    if remote_url.startswith("https://"):
        edge_candidates = [
            Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")) / "Microsoft/Edge/Application/msedge.exe",
            Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")) / "Microsoft/Edge/Application/msedge.exe",
        ]
        edge = next((str(p) for p in edge_candidates if p.exists()), None)
        if edge:
            profile = appdata / ("EdgeProfile-" + str(os.getpid()))
            profile.mkdir(parents=True, exist_ok=True)
            browser = subprocess.Popen([edge, "--user-data-dir=" + str(profile), "--no-first-run", "--disable-features=msEdgeSidebarV2", "--app=" + remote_url.rstrip("/") + "/customer"], close_fds=True)
            while browser.poll() is None:
                time.sleep(1)
        else:
            import webbrowser
            webbrowser.open(remote_url.rstrip("/") + "/customer")
            while True:
                time.sleep(60)
        return
    os.environ["SKILLVAYA_DB_PATH"] = str(appdata / "skillvaya.sqlite3")
    if getattr(sys, "frozen", False):
        os.environ["SKILLVAYA_EXE_PATH"] = sys.executable
    os.environ.pop("PORT", None)
    import app
    app.ROOT = str(bundle_root)
    app.HOST = "127.0.0.1"
    app.PORT = 8878

    server_thread = threading.Thread(target=app.main, name="SkillvayaServer", daemon=True)
    server_thread.start()
    url = "http://127.0.0.1:8878/"
    for _ in range(60):
        try:
            with urllib.request.urlopen(url + "healthz", timeout=1) as response:
                if response.status == 200:
                    break
        except Exception:
            time.sleep(0.25)
    else:
        raise RuntimeError("Skillvaya could not start its local service. Check whether port 8878 is already in use.")

    edge_candidates = [
        Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")) / "Microsoft/Edge/Application/msedge.exe",
        Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")) / "Microsoft/Edge/Application/msedge.exe",
    ]
    edge = next((str(p) for p in edge_candidates if p.exists()), None)
    if edge:
        profile = appdata / ("EdgeProfile-" + str(os.getpid()))
        profile.mkdir(parents=True, exist_ok=True)
        browser = subprocess.Popen([edge, "--user-data-dir=" + str(profile), "--no-first-run", "--disable-features=msEdgeSidebarV2", "--app=" + url], close_fds=True)
        while browser.poll() is None:
            time.sleep(1)
    else:
        import webbrowser
        webbrowser.open(url)
        while True:
            time.sleep(60)

if __name__ == "__main__":
    main()
