import json, os, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APPS = [os.path.join(ROOT, "app.py"), os.path.join(ROOT, "android-native", "app", "src", "main", "python", "app.py")]
DATA = [os.path.join(ROOT, "i18n_data.json"), os.path.join(ROOT, "android-native", "app", "src", "main", "python", "i18n_data.json")]


class LanguagesAndPlayOnlyContract(unittest.TestCase):
    """SV82-I18N: nine languages incl. Arabic right-to-left; SV82-PLAY-ONLY: plans are paid through Google Play only."""

    def read(self, p):
        with open(p, encoding="utf-8") as f:
            return f.read()

    def test_engine_and_picker(self):
        for p in APPS:
            s = self.read(p)
            for m in ("SV82-I18N", "function svTrApply(", "function svLoadLang(", 'if path=="/api/i18n":', 'id="svLangPick"',
                      "svInitLang();", "h.dir=l==='ar'?'rtl':'ltr'", ".message-bubble", "window.alert=m=>"):
                self.assertIn(m, s, p + " missing " + m)

    def test_translation_data(self):
        for p in DATA:
            d = json.load(open(p, encoding="utf-8"))
            self.assertTrue(d["version"])
            for lang in ("af", "zu", "xh", "st", "tn", "sw", "fr", "pt", "es", "de", "hi", "zh", "ar"):
                self.assertGreater(len(d["langs"][lang]), 900, p + " " + lang)

    def test_play_only(self):
        for p in APPS:
            s = self.read(p)
            self.assertIn("SV82-PLAY-ONLY", s)
            self.assertIn('return self.sendj({"error":SV_PLAY_ONLY,"play_only":True},410)  # SV82-PLAY-ONLY: every plan', s)
            self.assertIn(" svPlayOnlyNotice();return;", s)
            self.assertNotIn("Website checkout uses PayPal Live", s)


if __name__ == "__main__":
    unittest.main()
