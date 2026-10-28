"""Static guard tests for the isolated Google Play Billing implementation.

These checks complement (but do not replace) Play license-tester purchases.
"""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parent
APP = (ROOT / "app.py").read_text(encoding="utf-8")
JAVA = (ROOT / "android-native/app/src/main/java/za/co/skillvaya/app/PlayBillingBridge.java").read_text(encoding="utf-8")
GRADLE = (ROOT / "android-native/app/build.gradle").read_text(encoding="utf-8")
PREP = (ROOT / "prepare-play-bundle.ps1").read_text(encoding="utf-8")


class GooglePlayBillingGuards(unittest.TestCase):
    def test_all_four_product_ids_are_shared_by_client_and_server(self):
        products = (
            "skillvaya_local",
            "skillvaya_priority",
            "skillvaya_business_plus",
            "skillvaya_business_spotlight",
        )
        for product in products:
            with self.subTest(product=product):
                self.assertIn(product, JAVA)
                self.assertIn(product, APP)

    def test_monthly_and_annual_base_plan_selection_is_exact(self):
        self.assertIn("billing==='yearly'?'annual':'monthly'", APP)
        self.assertIn("find(x=>x.basePlanId===wanted)", APP)
        # Never silently fall back to a different billing period if a base plan is absent.
        self.assertNotIn("find(x=>x.basePlanId===wanted)||product?.offers?.[0]", APP)

    def test_server_verifies_with_android_publisher_before_entitlement(self):
        route = APP[APP.index('if path=="/api/google-play/verify":'):APP.index('if path=="/api/paypal/create-order":')]
        self.assertIn("subscriptionsv2().get", route)
        self.assertIn("SUBSCRIPTION_STATE_ACTIVE", route)
        self.assertIn("expiry_dt<=now_dt", route)
        self.assertIn("externalAccountIdentifiers", route)
        self.assertIn("google_play_subscriptions", route)

    def test_client_acknowledges_only_after_successful_server_verification(self):
        callback = JAVA[JAVA.index('if (status >= 200 && status < 300)'):JAVA.index('} catch (Exception e) {', JAVA.index('if (status >= 200 && status < 300)'))]
        self.assertIn('data.optBoolean("ok", false)', callback)
        self.assertIn("acknowledge(purchase)", callback)
        self.assertLess(callback.index('data.optBoolean("ok", false)'), callback.index("acknowledge(purchase)"))

    def test_obfuscated_account_id_encoding_matches_server_sha256_base64url(self):
        self.assertIn("MessageDigest.getInstance(\"SHA-256\")", JAVA)
        self.assertIn("Base64.URL_SAFE | Base64.NO_WRAP | Base64.NO_PADDING", JAVA)
        self.assertIn("base64.urlsafe_b64encode(hashlib.sha256(str(u[\"id\"]).encode()).digest()).decode().rstrip(\"=\")", APP)
        self.assertNotIn("return Base64.encodeToString(digest, Base64.URL_SAFE | Base64.NO_WRAP | Base64.NO_PADDING).substring(0, 64);", JAVA)

    def test_hosted_release_requires_https_staging_and_isolated_database_confirmation(self):
        self.assertIn("targetSdk 36", GRADLE)
        self.assertIn("SKILLVAYA_PLAY_STAGING_DATABASE_CONFIRMED", PREP)
        self.assertIn("Refusing to build the staging candidate against the live production website", PREP)
        self.assertIn("SKILLVAYA_PLAY_STAGING_URL", PREP)
        self.assertIn("SKILLVAYA_EXPECTED_DATABASE", APP)
        self.assertIn("SELECT current_database() AS name", APP)

    def test_subscription_changes_replace_existing_plan_instead_of_double_charging(self):
        self.assertIn("queryPurchasesAsync(existingParams", JAVA)
        self.assertIn("setOldPurchaseToken(existingPurchase.getPurchaseToken())", JAVA)
        self.assertIn("setSubscriptionProductReplacementParams", JAVA)
        self.assertIn("ReplacementMode.CHARGE_PRORATED_PRICE", JAVA)
        self.assertIn("ReplacementMode.DEFERRED", JAVA)
        self.assertIn("active.size() > 1", JAVA)

    def test_server_rejects_unknown_base_plan_and_retires_replaced_token(self):
        route = APP[APP.index('if path=="/api/google-play/verify":'):APP.index('if path=="/api/paypal/create-order":')]
        self.assertIn('base_plan not in ("monthly","annual")', route)
        self.assertIn('linkedPurchaseToken', route)
        self.assertIn("state='REPLACED'", route)
        rtdn = APP[APP.index('if path == "/api/google-play/rtdn":'):APP.index('if path == "/api/account/delete-request":')]
        self.assertIn('record["state"]=="REPLACED"', rtdn)

    def test_subscription_lifecycle_has_polling_fallback_without_pubsub(self):
        self.assertIn("refresh_google_play_subscription_for_user(int(u[\"id\"]))", APP)
        self.assertIn("total_seconds()>=600", APP)
        self.assertIn("subscriptionsv2().get", APP)
        self.assertIn("status='expired'", APP)
        self.assertIn("refresh_google_play_subscription_for_user(int(play_user[\"user_id\"]))", APP)
        self.assertIn("CREATE TABLE IF NOT EXISTS google_play_subscriptions", APP)

    def test_recurring_subscription_lifecycle_endpoint_is_authenticated(self):
        self.assertIn('if path == "/api/google-play/rtdn":', APP)
        self.assertIn("verify_oauth2_token", APP)
        self.assertIn("GOOGLE_PLAY_RTDN_AUDIENCE", APP)
        self.assertIn("GOOGLE_PLAY_RTDN_SERVICE_ACCOUNT_EMAIL", APP)


if __name__ == "__main__":
    unittest.main(verbosity=2)
