import os, re, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FILES = [os.path.join(ROOT, "app.py"), os.path.join(ROOT, "android-native", "app", "src", "main", "python", "app.py")]
POLICIES = [os.path.join(ROOT, "policies.html"), os.path.join(ROOT, "policy_page.py"),
            os.path.join(ROOT, "android-native", "app", "src", "main", "python", "policies.html"),
            os.path.join(ROOT, "android-native", "app", "src", "main", "python", "policy_page.py")]


class WorldwideFoundationContract(unittest.TestCase):
    """SV81-WORLD: countries, local currency at the same value as the rand price, local dates, privacy rights."""

    def read(self, path):
        with open(path, encoding="utf-8") as f:
            return f.read()

    def test_server_world_helpers(self):
        for path in FILES:
            s = self.read(path)
            for marker in ("SV81-WORLD", "SV_COUNTRIES={", "def sv_zar_to(", "def sv_paypal_amount(", "def sv_local_today(",
                           'if path=="/api/prices":', 'if path=="/api/account/export":', 'if path=="/api/me/country":',
                           "ALTER TABLE businesses ADD COLUMN country", "ALTER TABLE users ADD COLUMN country"):
                self.assertIn(marker, s, path + " missing " + marker)

    def test_prices_follow_the_rand_plan_prices(self):
        for path in FILES:
            s = self.read(path)
            self.assertIn('"monthly":round(v["monthly"]*rate,2)', s)
            self.assertIn('"yearly":round(v["monthly"]*11*rate,2)', s)
            self.assertIn('PLANS = {"local":{"name":"Local","monthly":105}', s, "rand base prices must stay the source of truth")

    def test_paypal_charges_local_currency_and_refunds_in_charged_currency(self):
        for path in FILES:
            s = self.read(path)
            self.assertIn("paypal_currency=sv_paypal_currency(", s)
            self.assertNotIn('paypal_currency="USD"\n', s)
            self.assertIn('"currency_code":_pcur', s)
            self.assertNotIn('"currency_code":"ZAR"', s, "PayPal cannot refund in ZAR")

    def test_no_hard_coded_rand_in_customer_money(self):
        for path in FILES:
            s = self.read(path)
            for gone in ("Budget in rand (optional)", "Quote amount in South African rand", "Total price (ZAR)",
                         "<label>Base price (R)</label>", "Fixed Rand amount", "across South Africa."):
                self.assertNotIn(gone, s, path + " still has " + gone)
            for js in ("function svMoney(", "function svCountry(", "function svPlanPrice(", "function svInjectCountryCard(",
                       "svDownloadMyData", 'class="sv-country-select"', "p.set('country',svCountry())"):
                self.assertIn(js, s, path + " missing " + js)

    def test_directory_local_dates_and_country_filter(self):
        for path in FILES:
            s = self.read(path)
            self.assertNotIn("==sa_today()", s)
            self.assertNotIn("today_sa", s)
            self.assertIn('item["currency"]=sv_currency(item["country"])', s)
            self.assertIn('"countrycodes":cc', s)

    def test_policies_cover_users_abroad(self):
        for path in POLICIES:
            s = self.read(path)
            self.assertIn("11A. Using Skillvaya outside South Africa", s)
            self.assertIn("8A. Your rights wherever you live", s)
            self.assertIn("Download my data", s)


if __name__ == "__main__":
    unittest.main()
