"""SV80: the Owner App fits phone screens and has Listings & Verification + Future Chat Launch areas."""
import pathlib, unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
COPIES = [ROOT / "app.py", ROOT / "android-native" / "app" / "src" / "main" / "python" / "app.py"]


class SV80OwnerMobileContract(unittest.TestCase):
    def check(self, s):
        owner = s[s.index('OWNER_APP_HTML = r"""'):s.index('OWNER_HTML = r"""')]
        # The grid can never be stretched wider than the phone by the scrolling menu.
        self.assertIn("/* SV80-OWNER-MOBILE", owner)
        self.assertIn(".layout{grid-template-columns:minmax(0,1fr)!important}", owner)
        self.assertIn("aside,main,nav,#panel{min-width:0;max-width:100%}", owner)
        # Tables become labelled cards on phones.
        self.assertIn("table{min-width:0!important;background:transparent}", owner)
        self.assertIn("td::before{content:attr(data-label)", owner)
        self.assertIn("'<td data-label=\"'+esc(headers[i]||'')+'\"><div class=\"cell\">'+x+'</div></td>'", owner)
        # New owner areas
        for a in ("listings", "futurechat"):
            self.assertIn('data-area="%s"' % a, owner)
        self.assertIn("else if(area==='listings')await renderListings();else if(area==='futurechat')await renderFutureChat()", owner)
        for fn in ("async function renderListings(", "async function ownerVerify(", "async function ownerListingStatus(", "async function renderFutureChat(", "async function ownerGrowthStats(", "async function ownerSuspendFromReport("):
            self.assertIn(fn, owner)
        self.assertIn("api('/api/admin/businesses-verify'", owner)

    def test_both_copies(self):
        for p in COPIES:
            with self.subTest(copy=str(p)):
                self.check(p.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
