"""Skillvaya staging retired: every request is forwarded to the live app.

Old test builds and home-screen shortcuts that still point at skillvaya-deletion-staging.onrender.com
showed an outdated app (old account screen, missing Services / Work Finder) with separate test accounts.
This tiny server sends them to the real app at https://skillvaya.onrender.com instead.
"""
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

LIVE = "https://skillvaya.onrender.com"
PAGE = ("<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>"
        "<title>Skillvaya has moved</title><meta http-equiv=refresh content='0;url=" + LIVE + "/customer-app'>"
        "<main style='font:17px system-ui;max-width:30rem;margin:18vh auto;padding:1rem;text-align:center'>"
        "<h1>Skillvaya</h1><p>This old test version has closed. Opening the real Skillvaya app&hellip;</p>"
        "<p><a href='" + LIVE + "/customer-app' style='font-size:19px'>Open Skillvaya</a></p>"
        "<p style='color:#567'>Please install the latest Skillvaya from Google Play or "
        "<a href='" + LIVE + "/downloads/Skillvaya.apk'>skillvaya.onrender.com</a>.</p></main>").encode("utf-8")
SW = (b"self.addEventListener('install',e=>self.skipWaiting());"
      b"self.addEventListener('activate',e=>e.waitUntil(caches.keys().then(k=>Promise.all(k.map(x=>caches.delete(x))))"
      b".then(()=>self.registration.unregister())));")

class H(BaseHTTPRequestHandler):
    def _go(self, body=True):
        path = self.path or "/"
        bare = path.split("?")[0]
        if bare in ("/healthz", "/health"):
            self.send_response(200); self.send_header("Content-Type", "text/plain"); self.end_headers()
            if body: self.wfile.write(b"ok")
            return
        if bare == "/sw.js":
            # Replace any old offline helper: wipe its saved screens and remove it.
            self.send_response(200); self.send_header("Content-Type", "application/javascript"); self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(SW))); self.end_headers()
            if body: self.wfile.write(SW)
            return
        if bare.startswith("/api/"):
            msg = b'{"error":"This old Skillvaya test version has closed. Please open the latest Skillvaya app."}'
            self.send_response(410); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(msg))); self.end_headers()
            if body: self.wfile.write(msg)
            return
        target = LIVE + ("/customer-app" if bare in ("/", "/index.html") else path)
        self.send_response(302); self.send_header("Location", target); self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Type", "text/html; charset=utf-8"); self.send_header("Content-Length", str(len(PAGE))); self.end_headers()
        if body: self.wfile.write(PAGE)
    def do_GET(self): self._go(True)
    def do_HEAD(self): self._go(False)
    def do_POST(self): self._go(True)
    def log_message(self, *a): pass

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    print("Skillvaya staging redirect listening on", port, flush=True)
    ThreadingHTTPServer(("0.0.0.0", port), H).serve_forever()
