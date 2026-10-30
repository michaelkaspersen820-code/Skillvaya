"""Regression guards for message/call speed and reliability (v74 performance round).

Findings that motivated each check:
  * svStartMessageLiveUpdates() was defined but never called, so message polling never ran;
  * every hosted-PostgreSQL query opened a brand-new connection (~1 s each from a distant region);
  * the 1-second call poll wrote to the database and re-read settings on every request;
  * chat sends waited on Firebase; calls had STUN only (no TURN relay) so they could not cross carrier NATs;
  * visible text had lost dashes/icons to literal '?' characters.
"""
from pathlib import Path
import os
import re
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
COPIES = {
    "server app.py": (ROOT / "app.py").read_text(encoding="utf-8"),
    "android app.py": (ROOT / "android-native/app/src/main/python/app.py").read_text(encoding="utf-8"),
}
WORKFINDER = {
    "static/workfinder.html": (ROOT / "static/workfinder.html").read_text(encoding="utf-8"),
    "android workfinder.html": (ROOT / "android-native/app/src/main/python/static/workfinder.html").read_text(encoding="utf-8"),
}


class RealtimeAndPerformanceContract(unittest.TestCase):
    def test_message_live_updates_are_actually_started_after_sign_in(self):
        for label, src in COPIES.items():
            self.assertGreaterEqual(src.count("svStartMessageLiveUpdates"), 2, label + ": defined but never called")
            self.assertIn("if(me)svStartMessageLiveUpdates();", src, label)

    def test_open_chat_uses_a_cheap_pulse_check_instead_of_downloading_everything(self):
        for label, src in COPIES.items():
            self.assertIn('if path=="/api/messages/pulse":', src, label)
            self.assertIn("async function svMessagePulse(){", src, label)
            self.assertIn("setInterval(()=>{window.svPulseTick++;", src, label)
            self.assertIn("api('/api/messages/pulse')", src, label)

    def test_postgres_connections_are_pooled_with_safe_defaults(self):
        for label, src in COPIES.items():
            self.assertIn("_PG_POOL_MAX", src, label)
            self.assertIn("raw.prepare_threshold = None", src, label)
            self.assertIn('os.environ.get("SKILLVAYA_DB_POOL", "on")', src, label)
            self.assertIn("raw.broken", src, label)
            self.assertIn("A pooled connection the server dropped while idle", src, label)

    def test_hot_path_does_not_write_or_requery_on_every_poll(self):
        for label, src in COPIES.items():
            self.assertIn('if _sweep_due("video_calls_missed",15):', src, label)
            self.assertIn("_GP_REFRESH_AT.get(int(user_id))", src, label)
            self.assertIn("_SETTING_CACHE.clear()", src, label)

    def test_indexes_exist_and_build_off_the_startup_path(self):
        for label, src in COPIES.items():
            self.assertGreaterEqual(len(re.findall(r'"CREATE INDEX IF NOT EXISTS idx_sv_', src)), 18, label)
            self.assertIn('threading.Thread(target=ensure_performance_indexes,name="skillvaya-indexes",daemon=True).start()', src, label)

    def test_chat_push_is_sent_in_the_background(self):
        server = COPIES["server app.py"]
        self.assertIn("def fcm_send_async(", server)
        send = server[server.index('if path=="/api/messages/send":'): server.index('if path=="/api/complaints":')]
        self.assertIn("fcm_send_async(recipient_id", send)
        self.assertNotIn("fcm_send_to_user(recipient_id", send)
        self.assertIn("def fcm_prewarm():", server)

    def test_calls_use_server_supplied_ice_servers_with_turn_support(self):
        for label, src in COPIES.items():
            self.assertIn('if path=="/api/ice-servers":', src, label)
            self.assertIn("iceServers:await svGetIceServers()", src, label)
            self.assertNotIn("new RTCPeerConnection({iceServers:[{urls:'stun:", src, label)

    def test_ice_server_builder_defaults_to_stun_and_adds_turn_only_when_configured(self):
        import app
        keys = ["SKILLVAYA_TURN_URLS", "SKILLVAYA_TURN_SECRET", "SKILLVAYA_TURN_USERNAME", "SKILLVAYA_TURN_CREDENTIAL"]
        saved = {k: os.environ.pop(k, None) for k in keys}
        try:
            plain = app.build_ice_servers({"id": 7})
            self.assertEqual(len(plain), 1)
            self.assertTrue(all(u.startswith("stun:") for u in plain[0]["urls"]))
            os.environ["SKILLVAYA_TURN_URLS"] = "turn:relay.example.test:3478,turns:relay.example.test:443?transport=tcp"
            os.environ["SKILLVAYA_TURN_SECRET"] = "s3cret"
            with_secret = app.build_ice_servers({"id": 7})
            self.assertEqual(len(with_secret), 2)
            self.assertTrue(with_secret[1]["username"].endswith(":7"))
            self.assertEqual(len(with_secret[1]["urls"]), 2)
            os.environ.pop("SKILLVAYA_TURN_SECRET")
            os.environ["SKILLVAYA_TURN_USERNAME"], os.environ["SKILLVAYA_TURN_CREDENTIAL"] = "u", "p"
            static = app.build_ice_servers()
            self.assertEqual((static[1]["username"], static[1]["credential"]), ("u", "p"))
        finally:
            for k, v in saved.items():
                if v is None: os.environ.pop(k, None)
                else: os.environ[k] = v

    def test_google_play_credentials_accept_the_hyphenated_host_variable_name(self):
        for label, src in COPIES.items():
            self.assertEqual(src.count('os.environ.get("GOOGLE_PLAY_SERVICE_ACCOUNT_JSON","").strip()'), 0, label)
            self.assertEqual(src.count("_google_play_credentials_json().strip()"), 3, label)
        import app
        saved = {k: os.environ.pop(k, None) for k in ("GOOGLE_PLAY_SERVICE_ACCOUNT_JSON", "GOOGLE_PLAY-SERVICE_ACCOUNT_JSON")}
        try:
            self.assertEqual(app._google_play_credentials_json(), "")
            os.environ["GOOGLE_PLAY-SERVICE_ACCOUNT_JSON"] = "{\"a\":1}"
            self.assertEqual(app._google_play_credentials_json(), "{\"a\":1}")
            os.environ["GOOGLE_PLAY_SERVICE_ACCOUNT_JSON"] = "{\"b\":2}"
            self.assertEqual(app._google_play_credentials_json(), "{\"b\":2}")
        finally:
            for k in ("GOOGLE_PLAY_SERVICE_ACCOUNT_JSON", "GOOGLE_PLAY-SERVICE_ACCOUNT_JSON"): os.environ.pop(k, None)
            for k, v in saved.items():
                if v is not None: os.environ[k] = v

    def test_android_webview_can_play_call_audio_and_asks_for_call_permissions_up_front(self):
        java = (ROOT / "android-native/app/src/main/java/za/co/skillvaya/app/MainActivity.java").read_text(encoding="utf-8")
        self.assertIn("settings.setMediaPlaybackRequiresUserGesture(false);", java)
        self.assertIn("CALL_STARTUP_PERMISSION_REQUEST", java)
        self.assertIn("Manifest.permission.RECORD_AUDIO", java[java.index("startupPermissions"):])
        self.assertIn("Manifest.permission.CAMERA", java[java.index("startupPermissions"):])

    def test_workfinder_users_can_actually_be_blocked_and_blocks_persist(self):
        for label, src in WORKFINDER.items():
            self.assertIn('onclick="blockUser(wfActivePartnerName)">Block</button>', src, label)
            self.assertIn("function saveBlockedUsers()", src, label)
            self.assertIn("localStorage.getItem('skillvaya.workfinder.blocked')", src, label)
            self.assertIn("wfConversations.filter(c=>!blockedUsers.has(c.partner_name))", src, label)

    def test_visible_text_has_no_corrupted_question_mark_glyphs(self):
        banned = ['bottom-tab-icon">?<', "PAID ? confirmed", "No ratings yet ? be", "Stars are ready ? the", "Thank you ? your",
                  "+' ? '+me.role", "Local ? R105", "Priority ? R210", "Business Plus ? R500", "Business Spotlight ? R1,000"]
        for label, src in COPIES.items():
            for bad in banned:
                self.assertNotIn(bad, src, "%s still contains corrupted text: %s" % (label, bad))
            self.assertIn('<span class="bottom-tab-icon">\u25c6</span><span>Work Finder</span>', src, label)
        for label, src in WORKFINDER.items():
            self.assertNotIn("'?? Upload portfolio'", src, label)


if __name__ == "__main__":
    unittest.main()
