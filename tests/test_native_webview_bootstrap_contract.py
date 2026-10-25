"""Regression guards for the Android WebView's customer, owner, and WorkFinder routes.

These checks deliberately fail CI if a later UI/deployment change reintroduces the
owner-screen readiness false negative or sends an owner screen to the customer route.
"""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
ACTIVITY = (ROOT / "android-native/app/src/main/java/za/co/skillvaya/app/MainActivity.java").read_text(encoding="utf-8")
SERVER = (ROOT / "app.py").read_text(encoding="utf-8")


class NativeWebViewBootstrapContract(unittest.TestCase):
    def test_owner_readiness_does_not_depend_on_customer_title_or_text(self):
        self.assertRegex(ACTIVITY, r"if\s*\(owner\)\s*return\s+!!\(b&&b\.children\.length>0&&\(document\.getElementById\('loginScreen'\)\|\|document\.getElementById\('appShell'\)\)\)")
        self.assertIn("var owner=p.indexOf('/owner-app')===0", ACTIVITY)
        self.assertIn("var customer=p.indexOf('/customer-app')===0", ACTIVITY)

    def test_retry_preserves_owner_route_and_is_bounded(self):
        retry = re.search(r"private final Runnable retryHostedPage.*?\n\s*};", ACTIVITY, re.S)
        self.assertIsNotNone(retry, "Native hosted-page recovery runnable must remain present")
        body = retry.group(0)
        self.assertIn("hostedRetryCount < 5", body, "Recovery must be bounded")
        self.assertIn('getPath().startsWith("/owner-app")', body, "Owner route must be preserved during recovery")
        self.assertIn('targetPath = "/owner-app"', body)
        self.assertIn('baseUrl + targetPath + "?native_refresh="', body)

    def test_loading_splash_only_hides_after_app_is_recognized(self):
        self.assertIn("if (\"true\".equals(value))", ACTIVITY)
        self.assertIn("hostedAppReady = true", ACTIVITY)
        self.assertIn("webView.setVisibility(ViewGroup.VISIBLE)", ACTIVITY)
        self.assertIn("loadingHandler.postDelayed(retryHostedPage, 2200)", ACTIVITY)

    def test_owner_and_workfinder_routes_remain_registered(self):
        self.assertRegex(SERVER, r'if\s+path\s*==\s*[\"\']?/owner-app')
        self.assertIn('if path == "/workfinder"', SERVER)
        self.assertIn('OWNER_APP_HTML', SERVER)
        self.assertIn('static", "workfinder.html"', SERVER)


if __name__ == "__main__":
    unittest.main(verbosity=2)
