import os, sys, time, threading, subprocess, urllib.request, shutil
from pathlib import Path

def _ps_quote(value):
    return "'" + str(value).replace("'", "''") + "'"

def ensure_windows_install(bundle_root):
    # A browser cannot silently create a desktop shortcut from a downloaded EXE.
    # First launch copies this self-contained app into LocalAppData and creates shortcuts.
    if not getattr(sys, "frozen", False):
        return False
    local = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local")))
    install_dir = local / "Programs" / "Skillvaya"
    install_exe = install_dir / "Skillvaya.exe"
    current_exe = Path(sys.executable).resolve()
    install_dir.mkdir(parents=True, exist_ok=True)
    if current_exe != install_exe.resolve():
        shutil.copy2(current_exe, install_exe)
    icon_src = bundle_root / "skillvaya.ico"
    icon_dest = install_dir / "skillvaya.ico"
    if icon_src.exists() and icon_src.resolve() != icon_dest.resolve():
        shutil.copy2(icon_src, icon_dest)
    target = _ps_quote(install_exe)
    icon = _ps_quote(icon_dest if icon_dest.exists() else install_exe)
    ps = (
        "$ErrorActionPreference='Stop';"
        "$desktop=[Environment]::GetFolderPath('Desktop');"
        "$start=Join-Path ([Environment]::GetFolderPath('Programs')) 'Skillvaya';"
        "New-Item -ItemType Directory -Path $start -Force | Out-Null;"
        "$ws=New-Object -ComObject WScript.Shell;"
        f"$target={target};$icon={icon};"
        "foreach($p in @((Join-Path $desktop 'Skillvaya.lnk'),(Join-Path $start 'Skillvaya.lnk'))){"
        "$s=$ws.CreateShortcut($p);$s.TargetPath=$target;$s.WorkingDirectory=(Split-Path $target);"
        "$s.IconLocation=$icon+',0';$s.Description='Skillvaya - sign in and open your workspace';$s.Save()}"
    )
    try:
        subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps],
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20)
    except Exception:
        pass
    if current_exe != install_exe.resolve():
        flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        subprocess.Popen([str(install_exe)], cwd=str(install_dir), close_fds=True, creationflags=flags)
        return True
    return False

def main():
    bundle_root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    if ensure_windows_install(bundle_root):
        return
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
            profile = appdata / "EdgeProfile"
            profile.mkdir(parents=True, exist_ok=True)
            launch_url = remote_url.rstrip("/")
            if not launch_url.endswith("/login"):
                launch_url += "/login"
            browser = subprocess.Popen([edge, "--user-data-dir=" + str(profile), "--no-first-run", "--disable-features=msEdgeSidebarV2", "--app=" + launch_url], close_fds=True)
            while browser.poll() is None:
                time.sleep(1)
        else:
            import webbrowser
            launch_url = remote_url.rstrip("/")
            if not launch_url.endswith("/login"):
                launch_url += "/login"
            webbrowser.open(launch_url)
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
    url = "http://127.0.0.1:8878/login"
    health_url = "http://127.0.0.1:8878/healthz"
    for _ in range(60):
        try:
            with urllib.request.urlopen(health_url, timeout=1) as response:
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
        profile = appdata / "EdgeProfile"
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
