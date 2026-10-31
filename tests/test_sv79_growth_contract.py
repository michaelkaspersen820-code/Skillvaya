"""SV79: trust badges, near me, availability, sharing (Future Chat first), data saver, Future Chat launch list."""
import pathlib, unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
COPIES = [ROOT / "app.py", ROOT / "android-native" / "app" / "src" / "main" / "python" / "app.py"]


class SV79GrowthContract(unittest.TestCase):
    def check(self, s):
        # Server
        for col in ("lat", "lng", "available_on", "verified_at", "verify_requested_at"):
            self.assertIn('("%s",' % col, s)
        self.assertIn("CREATE TABLE IF NOT EXISTS futurechat_waitlist(", s)
        self.assertIn("CREATE TABLE IF NOT EXISTS geo_cache(", s)
        self.assertIn('delete_where("futurechat_waitlist", "user_id=?", [user_id])', s)
        # Provider location is town-level and never sent to customers.
        self.assertIn('for _k in ("lat","lng","verified_at","verify_requested_at","available_on"): item.pop(_k,None)', s)
        self.assertIn('round(float(data[0]["lat"]),2),round(float(data[0]["lon"]),2)', s)
        self.assertIn('if u.get("role")!="admin": return self.sendj({"error":"Only the Skillvaya owner can verify providers."},403)', s)
        for route in ('/api/provider/presence', '/api/provider/verification-request', '/api/admin/businesses-verify', '/api/futurechat/notify',
                      '/api/admin/futurechat', '/api/futurechat/status', '/api/provider/tools'):
            self.assertIn('path=="%s"' % route, s)
        self.assertIn('if path.startswith("/p/"):', s)
        self.assertIn('if path.startswith("/api/businesses/") and path.endswith("/photos"):', s)
        # Client
        self.assertEqual(s.count('<option value="near">Near me</option><option value="available">Available today</option>'), 2)
        self.assertEqual(s.count("svTrustBadges(b)+svResponseBadge(b)+ratingMarkup("), 3)
        self.assertIn("svLoadPortfolio(Number(b.id),!!b.has_photos)", s)
        self.assertIn('id="svFutureChatCard"', s)
        self.assertIn("onclick=\"svShareProvider('+Number(b.id)+')\"", s)
        sheet = s[s.index("function svShareSheet("):]
        self.assertLess(sheet.index('id="svShareFC"'), sheet.index('id="svShareOther"'))  # Future Chat is the first share option
        self.assertIn("function svDataSaver()", s)
        self.assertNotIn("document.body.appendChild(b)", s)

    def test_both_copies(self):
        for p in COPIES:
            with self.subTest(copy=str(p)):
                self.check(p.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
