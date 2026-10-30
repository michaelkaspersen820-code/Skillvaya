"""Regression guards for the one-header standard (SV75-HEADERS-01 / SV75-WF-HEADERS-01).

Found by a real-browser audit of every screen at phone width (v7.1.7.2):
  * screen headers ranged from 62px to 284px tall with titles from 19px to 52px (Services workstation hero was 284px);
  * sticky headers used a hard-coded 76px offset, so content showed above them when the masthead was hidden
    and they overlapped the masthead when it was taller than 76px;
  * WorkFinder page titles scrolled away while the rest of the app kept headers on screen.
These are static contract checks; the pixel-level proof is the Playwright audit (hdr_audit.py) run before release.
"""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
APPS = {
    "server app.py": (ROOT / "app.py").read_text(encoding="utf-8"),
    "android app.py": (ROOT / "android-native/app/src/main/python/app.py").read_text(encoding="utf-8"),
}
WFS = {
    "server workfinder.html": (ROOT / "static/workfinder.html").read_text(encoding="utf-8"),
    "android workfinder.html": (ROOT / "android-native/app/src/main/python/static/workfinder.html").read_text(encoding="utf-8"),
}
START = "/* SV75-HEADERS-01: one compact"
END = "</style></head><body>\n<div id=\"svSplash\""
BARS = [
    "#providerStudioHeading", ".destination-hero", ".sv-workstation-hero", ".sv-tool-heading", "#settings .profile-heading",
    "#messagesScreen .messages-app-header", ".category-screen-head", "#accountSubspace .account-subspace-top", ".sv-subtest-topbar",
    "#terms .card>h2", "#providerDetailScreen>.ghost",
]


def block(src):
    i = src.index(START)
    return src[i:src.index(END, i)]


class OneHeaderStandardContract(unittest.TestCase):
    def test_every_screen_header_is_in_the_standard(self):
        for name, src in APPS.items():
            css = block(src)
            for sel in BARS:
                self.assertIn(sel, css, "%s: %s is not covered by the header standard" % (name, sel))

    def test_standard_numbers_are_small_and_shared(self):
        for name, src in APPS.items():
            css = block(src)
            self.assertIn("--sv-hdr-min:62px", css, name)
            self.assertIn("--sv-hdr-title:20px", css, name)
            self.assertIn("--sv-hdr-sub:12px", css, name)
            self.assertIn("max-height:84px", css, name)
            # a tall hero must not be able to come back: titles clamp to one line, subtitles to one line
            self.assertIn("text-overflow:ellipsis", css, name)
            self.assertIn("-webkit-line-clamp:1", css, name)

    def test_sticky_bars_follow_the_visible_masthead(self):
        for name, src in APPS.items():
            css = block(src)
            self.assertIn("top:var(--sv-screen-header-top,0px)", css, name)
            self.assertNotIn("var(--sv-screen-header-top,76px)", css, name + ": hard-coded 76px fallback is back")
            self.assertIn("window.svSyncHeaderOffset=sync", src, name)
            self.assertIn("document.body.style.setProperty('--sv-screen-header-top'", src, name)
            self.assertIn("getBoundingClientRect().bottom", src, name)

    def test_standard_overrides_the_older_header_rules(self):
        for name, src in APPS.items():
            start = src.index(START)
            for older in ("SV57-ACCOUNT-HEADER-01", "padding-top:178px!important", "#providerStudioHeading{position:sticky!important;top:var(--sv-screen-header-top,76px)"):
                last = src.rfind(older, 0, start)
                self.assertGreater(last, -1, "%s: expected older rule %r before the standard" % (name, older))
            self.assertIn(":not(#z):not(#z)", block(src), name + ": specificity boost missing, older !important id rules would win")

    def test_account_header_stays_compact_and_content_clears_it(self):
        for name, src in APPS.items():
            css = block(src)
            self.assertIn("body.account-screen-mode main.wrap:not(#z):not(#z){padding-top:calc(var(--sv-hdr-min) + 14px)!important}", css, name)
            self.assertIn("position:fixed!important;left:0!important;right:0!important", css, name)

    def test_account_subspace_cards_start_under_the_compact_bar(self):
        for name, src in APPS.items():
            self.assertIn("account-subspace-card:not(#z):not(#z){top:calc(var(--sv-hdr-min) + 12px)!important}", block(src), name)

    def test_phone_masthead_matches_the_bar_height(self):
        for name, src in APPS.items():
            css = block(src)
            self.assertIn(".nav{min-height:62px!important", css, name)
            self.assertIn(".studio-header-tagline{display:none!important}", css, name)

    def test_terms_page_header_is_compact_and_sticky(self):
        for name, src in APPS.items():
            i = src.index("TERMS_PAGE_HTML = r")
            j = src.index("Skillvaya Terms & Conditions</title>", i)
            terms = src[j:j + 30000]
            self.assertIn("SV75-HEADERS-01 terms page: compact sticky header", terms, name)
            self.assertIn(".top{position:sticky;top:0;z-index:50", terms, name)
            self.assertIn(".top h1{font-size:20px!important", terms, name)

    def test_owner_dashboard_title_bar_is_sticky(self):
        for name, src in APPS.items():
            self.assertIn("main>.top:first-child{position:sticky;top:0;z-index:40", src, name)

    def test_app_copies_share_one_identical_standard(self):
        blocks = {n: block(s) for n, s in APPS.items()}
        self.assertEqual(len(set(blocks.values())), 1, "server and Android header CSS differ")

    def test_workfinder_pages_get_the_same_sticky_header(self):
        for name, src in WFS.items():
            self.assertIn("SV75-WF-HEADERS-01", src, name)
            self.assertIn("position:sticky;top:var(--wf-top,60px)", src, name)
            self.assertIn("--wf-hdr-title:20px", src, name)
            self.assertIn("min-height:62px", src, name)
            self.assertIn("className='wf-pagehead'", src, name)
            self.assertIn("new MutationObserver(decorate).observe(c,{childList:true})", src, name)
            self.assertIn(".top strong,.top .sub{display:block;max-width:100%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}", src, name)
            # overflow-x:hidden on html+body breaks position:sticky, so the clip fallback must stay
            self.assertIn("@supports(overflow:clip){html,body{overflow-x:clip!important}}", src, name)
            # the chat header used to sit at y=12 behind the 60px app bar (Back, name and Block were unreachable)
            self.assertIn(".content.chatpage{padding-top:var(--wf-top,60px)!important}", src, name)

    def test_workfinder_copies_are_identical(self):
        a, b = WFS.values()
        self.assertEqual(a, b, "server and Android workfinder.html differ")

    def test_policy_and_deletion_pages_have_a_sticky_compact_header(self):
        for fname in ("policies.html", "account_deletion.html"):
            src = (ROOT / fname).read_text(encoding="utf-8")
            self.assertIn("SV75-HEADERS-01", src, fname)
            self.assertIn(".top{position:sticky;top:0;z-index:50", src, fname)


if __name__ == "__main__":
    unittest.main()
