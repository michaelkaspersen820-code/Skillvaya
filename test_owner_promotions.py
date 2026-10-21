import gc, json, os, tempfile, threading, urllib.request, urllib.error
import app
from http.server import ThreadingHTTPServer

def main():
    db = os.path.join(tempfile.gettempdir(), "skillvaya_owner_promotions_regression.sqlite3")
    try:
        os.remove(db)
    except OSError:
        pass
    app.DB = db
    app.SESSIONS.clear()
    app.init()
    server = ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = "http://127.0.0.1:" + str(server.server_address[1])
    def request(path, method="GET", data=None, expected=200):
        req = urllib.request.Request(
            base + path, method=method,
            headers={"Content-Type": "application/json"},
            data=None if data is None else json.dumps(data).encode("utf-8"))
        try:
            with urllib.request.urlopen(req, timeout=5) as response:
                status, raw = response.status, response.read()
        except urllib.error.HTTPError as exc:
            status, raw = exc.code, exc.read()
        assert status == expected, (path, status, raw[:300])
        return json.loads(raw) if raw else {}
    try:
        assert "owner-control" not in app.HTML
        assert "My Businesses & Promotions" in app.OWNER_HTML
        assert 'data-tab="payments"' not in app.OWNER_APP_HTML
        assert 'data-tab="promotions"' in app.OWNER_APP_HTML
        assert 'class="tabs"' in app.OWNER_APP_HTML
        assert 'My businesses & promotions (free)' in app.OWNER_HTML
        created = request("/api/admin/owner-promotions", "POST", {
            "kind": "app", "business_name": "Test Studio", "title": "Test App",
            "category": "Web & software developers", "description": "Regression test",
            "target_url": "https://example.com", "image_url": ""
        }, 201)
        assert created["owner_free"] is True
        rows = request("/api/admin/owner-promotions")["items"]
        assert len(rows) == 1 and rows[0]["owner_free"] == 1
        public = request("/api/owner-promotions")["items"]
        assert len(public) == 1 and public[0]["title"] == "Test App"
        request("/api/admin/owner-promotions/" + str(created["id"]), "POST", {"status": "paused"})
        assert request("/api/owner-promotions")["items"] == []
        request("/api/admin/owner-promotions/" + str(created["id"]), "POST", {"status": "active"})
        assert len(request("/api/owner-promotions")["items"]) == 1
        print("PASS owner promotions: owner tab, persistent records, fee exemption, public publishing, pause and republish")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
    gc.collect()
    try:
        os.remove(db)
    except OSError:
        pass

if __name__ == "__main__":
    main()
