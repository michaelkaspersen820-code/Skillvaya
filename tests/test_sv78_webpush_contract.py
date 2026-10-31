"""SV78: browser web push (iPhone home-screen app, computers) stays wired up without touching the Android app."""
import pathlib, unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
MAIN = ROOT / "app.py"
COPIES = [MAIN, ROOT / "android-native" / "app" / "src" / "main" / "python" / "app.py"]


class SV78WebPushContract(unittest.TestCase):
    def check(self, s):
        self.assertIn("CREATE TABLE IF NOT EXISTS webpush_subscriptions(", s)
        self.assertIn("CREATE TABLE IF NOT EXISTS webpush_keys(", s)
        self.assertIn('delete_where("webpush_subscriptions", "user_id=?", [user_id])', s)
        self.assertIn('if path=="/api/webpush/key":', s)
        self.assertIn('if path in ("/api/webpush/subscribe","/api/webpush/unsubscribe","/api/webpush/test"):', s)
        # Only real push services are contacted (no server-side request forgery).
        self.assertIn("def _sv_wp_host_ok(endpoint):", s)
        self.assertIn("if not _sv_wp_host_ok(ep): continue", s)
        # Service worker shows alerts and opens the app.
        self.assertIn("self.addEventListener('push'", s)
        self.assertIn("self.addEventListener('notificationclick'", s)
        # Client: never inside the Android app; subscribes after sign-in; forgets on sign-out.
        self.assertIn("function svIsNativeApp(){return /SkillvayaNative/.test(", s)
        self.assertIn("function svStartMessageLiveUpdates(){svEnsureNotificationBell();try{svWebPushSync()}catch(_){};", s)
        self.assertIn("async function logout(){try{await svWebPushForget()}catch(_){}", s)
        self.assertIn("Add to Home Screen", s)

    def test_both_copies(self):
        for p in COPIES:
            with self.subTest(copy=str(p)):
                self.check(p.read_text(encoding="utf-8"))

    def test_server_copy_sends_web_push_with_every_firebase_alert(self):
        s = MAIN.read_text(encoding="utf-8")
        fn = s[s.index("def fcm_send_to_user("):]
        fn = fn[:fn.index("\ndef ")]
        self.assertIn("webpush_send_async(user_id, title, body, data)", fn)
        self.assertLess(fn.index("webpush_send_async"), fn.index("FIREBASE_SERVICE_ACCOUNT_JSON"))

    def test_deploy_files(self):
        self.assertIn("pywebpush", (ROOT / "requirements.txt").read_text(encoding="utf-8"))
        self.assertNotIn("plan: free", (ROOT / "render.yaml").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
