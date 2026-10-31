"""SV77: missed-call notices and provider response-time badges stay wired up in both app.py copies."""
import pathlib, unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
COPIES = [ROOT / "app.py", ROOT / "android-native" / "app" / "src" / "main" / "python" / "app.py"]


class SV77FeaturesContract(unittest.TestCase):
    def check(self, s):
        # Missed calls: hang-up while ringing and the 5-minute sweep both record + notify.
        self.assertIn("def sv_missed_call_notice(c, call):", s)
        self.assertIn('if action=="end" and call["status"]=="ringing" and int(u["id"])==int(call["caller_id"]): status="missed"', s)
        self.assertIn('if status=="missed": sv_missed_call_notice(c,dict(call))', s)
        self.assertIn("for row in swept: sv_missed_call_notice(c,dict(row))", s)
        self.assertIn('"type":"missed_call"', s)
        # Missed-call notices never count toward response time.
        self.assertIn('_SV_NON_CHAT=("Video call invitation","Missed voice call","Missed video call")', s)
        # Response badge: computed server-side, rendered on every provider card/profile that shows ratings.
        self.assertIn('item["response_label"]=labels.get(int(item["id"]),"")', s)
        self.assertIn("function svResponseBadge(b)", s)
        self.assertEqual(s.count("svResponseBadge(b)+ratingMarkup(b.id,b.rating,b.rating_count,b.my_rating)"), 3)

    def test_both_copies(self):
        for p in COPIES:
            with self.subTest(copy=str(p)):
                self.check(p.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
