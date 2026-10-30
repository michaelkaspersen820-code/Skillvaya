"""Regression guards for speed (SV76-PERF-01/02, SV76-SPEED-01).

Measured with a real browser (phone CPU x4 slower, 300 ms network latency) and real PostgreSQL behind a delayed proxy:
  * every database call used to cost 3 network round trips (implicit BEGIN, the query, COMMIT) and every signed-in request paid it twice
    (session check + data), so opening Messages cost 9 round trips and /api/me 6;
  * start-up waited for /api/me, then loaded the directory, then waited up to 1.8 s for categories, before the splash screen went away;
  * opening Messages / a conversation / the Services tab always waited for the network, even when the data was already on the phone.
These are static contract checks plus SQLite behaviour checks; the numbers come from the Playwright benchmark run before release.
"""
from pathlib import Path
import os
import re
import sqlite3
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
APPS = {
    "server app.py": (ROOT / "app.py").read_text(encoding="utf-8"),
    "android app.py": (ROOT / "android-native/app/src/main/python/app.py").read_text(encoding="utf-8"),
}


def function_text(src, name):
    m = re.search(r"(?:async\s+)?function\s+%s\s*\(" % re.escape(name), src)
    assert m, name
    i = m.start(); depth_p = 1; p = m.end()
    while depth_p:
        depth_p += {"(": 1, ")": -1}.get(src[p], 0); p += 1
    j = src.index("{", p); depth = 0; k = j; instr = None; esc = False
    while True:
        c = src[k]
        if instr:
            if esc: esc = False
            elif c == "\\": esc = True
            elif c == instr: instr = None
        elif c in "'\"`": instr = c
        elif c == "{": depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0: break
        k += 1
    return src[i:k + 1]


class DatabaseRoundTripContract(unittest.TestCase):
    def test_connections_are_autocommit_and_open_a_transaction_only_for_writes(self):
        for name, src in APPS.items():
            self.assertIn("connect_timeout=15, autocommit=True", src, name)
            self.assertIn("psycopg.connect(DATABASE_URL, row_factory=hybrid_row, autocommit=True)", src, name)
            self.assertIn("if self.raw.info.transaction_status == _PG_IDLE and not _pg_is_read(sql):\n                self.raw.execute(\"BEGIN\")", src, name)
            self.assertIn("head.startswith((\"SELECT\", \"SHOW \", \"EXPLAIN\"))", src, name)

    def test_commit_and_rollback_cost_nothing_when_no_transaction_is_open(self):
        for name, src in APPS.items():
            self.assertIn("if self.raw.info.transaction_status != _PG_IDLE: return self.raw.commit()", src, name)
            self.assertIn("if self.raw.info.transaction_status != _PG_IDLE: return self.raw.rollback()", src, name)

    def test_one_round_trip_helpers_exist_with_sqlite_fallbacks(self):
        for name, src in APPS.items():
            for needle in ("def execute_atomic(self, sql, params=()):", "def execute_batch(self, statements):", "with self.raw.pipeline():",
                           "def db_atomic(c, sql, params=()):", "def db_batch(c, statements):"):
                self.assertIn(needle, src, "%s: %s" % (name, needle))
            self.assertIn("return [c.execute(s, p).fetchall() for s, p in statements]", src, name)

    def test_hot_endpoints_use_them(self):
        for name, src in APPS.items():
            self.assertIn("call_rows,signals=db_batch(c,[", src, name + ": call sync must read the call and its signals in one trip")
            self.assertIn("row=db_atomic(c,\"INSERT INTO video_call_signals", src, name)
            self.assertIn("db_atomic(c,\"UPDATE video_calls SET status='accepted'", src, name)
            self.assertIn("db_atomic(c,\"UPDATE messages SET read_at=?", src, name)
            self.assertIn("WITH m AS (INSERT INTO messages", src, name + ": message + enquiry must be one statement")
            self.assertIn("WITH vc AS (INSERT INTO video_calls", src, name + ": call row + chat invitation must be one statement")
            self.assertIn("u=self.require(want_photo=True)", src, name + ": /api/me must be a single query")

    def test_session_check_still_validates_expiry_every_time(self):
        for name, src in APPS.items():
            self.assertIn("if row[\"expires_at\"] <= now():", src, name)
            self.assertIn("FROM auth_sessions s JOIN users u ON u.id=s.user_id WHERE s.token=?", src, name)

    def test_sqlite_fallbacks_behave(self):
        ns = {}
        src = APPS["server app.py"]
        start = src.index("def db_atomic(c, sql, params=()):")
        end = src.index("def fcm_send_to_user(", start)
        exec(compile(src[start:end], "helpers", "exec"), ns)
        with tempfile.TemporaryDirectory() as tmp:
            c = sqlite3.connect(os.path.join(tmp, "t.sqlite3"))
            c.execute("CREATE TABLE t(id INTEGER PRIMARY KEY, v TEXT)")
            ns["db_atomic"](c, "INSERT INTO t(v) VALUES(?)", ("a",)); ns["db_atomic"](c, "INSERT INTO t(v) VALUES(?)", ("b",))
            first, second = ns["db_batch"](c, [("SELECT v FROM t WHERE id=?", (1,)), ("SELECT v FROM t WHERE id=?", (99,))])
            self.assertEqual([r[0] for r in first], ["a"])
            self.assertEqual(second, [])
            c.close()


class InstantScreensContract(unittest.TestCase):
    def test_startup_runs_everything_in_parallel(self):
        for name, src in APPS.items():
            init = function_text(src, "init")
            self.assertNotIn("await sessionInfo()", init, name + ": start-up must not wait for the session before anything else")
            self.assertNotIn("1800", init, name + ": categories must not hold the splash screen")
            for needle in ("try{svPaintCachedDirectory()}catch(e){}", "const svSessionP=sessionInfo()", "const svDirectoryP=loadBusinesses();", "const svCategoriesP=api('/api/categories')",
                           "if(!svDirectoryHadCache)await Promise.race([svDirectoryP,new Promise(r=>setTimeout(r,1500))]);"):
                self.assertIn(needle, init, "%s: %s" % (name, needle))

    def test_directory_paints_from_cache_and_fetches_favourites_in_parallel(self):
        for name, src in APPS.items():
            self.assertIn("function svRenderDirectory(d){", src, name)
            load = function_text(src, "loadBusinesses")
            self.assertIn("const svFavP=", load, name)
            self.assertIn("svSaveDirectoryCache(p,d);svRenderDirectory(d);", load, name)
            self.assertNotIn("await api('/api/favorites')", load, name + ": favourites must not be fetched after the directory")
            pick = function_text(src, "pickCat")
            self.assertIn("svFullDirectory.filter(", pick, name + ": a category must open from the list already on the phone")

    def test_directory_cache_never_stores_a_users_personal_ratings(self):
        for name, src in APPS.items():
            self.assertIn("delete c.my_rating", src, name)

    def test_messages_open_from_cache_and_conversations_open_warm(self):
        for name, src in APPS.items():
            threads = function_text(src, "loadMessageThreads")
            self.assertIn("svCacheGet(key)", threads, name)
            self.assertIn("svCacheSet(key,", threads, name)
            self.assertIn("window.svMessagesItems={userId:Number(me.id)", threads, name)
            conv = function_text(src, "openMessageConversation")
            for needle in ("let svWarm=", "const d=svWarm?{items:svWarm}:await api('/api/messages');", "const buildThread=(its)=>", "if(svWarm){api('/api/messages').then(fresh=>"):
                self.assertIn(needle, conv, "%s: %s" % (name, needle))

    def test_anything_that_adds_a_message_discards_the_in_memory_inbox(self):
        for name, src in APPS.items():
            api = function_text(src, "api") if False else src[src.index("async function api(path,opts={}){/* SV76-SPEED-01"):][:700]
            self.assertIn("window.svMessagesItems=null", api, name)
            self.assertIn("'/api/messages/read'", api, name + ": marking read must not throw the warm copy away")
            self.assertIn("'/api/video-calls'", api, name + ": a call invitation is a chat message")

    def test_provider_tools_show_from_the_last_verified_plan(self):
        for name, src in APPS.items():
            ws = function_text(src, "loadProviderWorkstation")
            for needle in ("sv_ws_profile_v1_", "wsApply(wsCached.business);", "loadProviderWorkstation().catch(()=>{})"):
                self.assertIn(needle, ws, "%s: %s" % (name, needle))

    def test_private_caches_are_wiped_on_logout(self):
        for name, src in APPS.items():
            self.assertIn("function svClearUserCaches(){", src, name)
            self.assertIn("k.indexOf('sv_message_cache_v54_')===0||k.indexOf('sv_ws_profile_v1_')===0", src, name)
            self.assertIn("try{svClearUserCaches()}catch(e){}token='';me=null;", src, name)

    def test_server_and_android_copies_share_the_speed_code(self):
        a, b = APPS.values()
        for fn in ("init", "loadBusinesses", "openMessageConversation", "loadMessageThreads", "loadProviderWorkstation", "pickCat"):
            self.assertEqual(function_text(a, fn), function_text(b, fn), fn)


class AppShellCachingContract(unittest.TestCase):
    def test_app_pages_have_validators(self):
        for name, src in APPS.items():
            self.assertIn('etag=\'"\'+hashlib.sha1(customer_html).hexdigest()[:24]+\'"\'', src, name)
            self.assertIn('self.send_response(304); self.send_header("ETag",etag)', src, name)
            self.assertIn("wf_etag = '\"' + hashlib.sha1(workfinder_html).hexdigest()[:24] + '\"'", src, name)
            self.assertIn('.replace("W/","").strip()==etag', src, name + ": a CDN may weaken the ETag, the comparison must tolerate W/")

    def test_logo_and_icon_are_cached_for_a_day(self):
        for name, src in APPS.items():
            self.assertIn('self.send_header("Content-Type","image/jpeg"); self.send_header("Cache-Control","public, max-age=86400");', src, name)
            self.assertIn('self.send_header("Content-Type","image/svg+xml; charset=utf-8"); self.send_header("Cache-Control","public, max-age=86400");', src, name)

    def test_service_worker_never_blocks_on_a_sleeping_server(self):
        for name, src in APPS.items():
            self.assertIn("const CACHE='skillvaya-shell-v4-fast';", src, name)
            self.assertIn("'/terms','/workfinder'];", src, name)
            self.assertIn("new Promise(res=>setTimeout(()=>res(cached),2500))", src, name)
            self.assertIn("if(!cached)return net.catch(offline);", src, name)
            self.assertIn("fetch(e.request,{cache:'no-cache'})", src, name)
            self.assertNotIn("{cache:'no-store'}).catch(()=>new Response", src, name + ": old always-network handler is back")


class WorkFinderSpeedContract(unittest.TestCase):
    def test_workfinder_loads_its_data_in_one_trip(self):
        for rel in ("static/workfinder.html", "android-native/app/src/main/python/static/workfinder.html"):
            src = (ROOT / rel).read_text(encoding="utf-8")
            self.assertIn("wfApi('/api/workfinder/profile'),loadWfConversations()]);", src, rel)
            self.assertNotIn("wfSavedBusinessFiles=bf?.files||[]}await loadWfConversations()", src, rel)
            self.assertIn("Promise.all([wfApi('/api/me').then(", src, rel)
            self.assertIn("loadWfData(true)]).then(()=>go(3))", src, rel)


if __name__ == "__main__":
    unittest.main()
