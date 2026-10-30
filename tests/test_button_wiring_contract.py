"""Regression guards for working buttons: every wired handler must exist, and known-dead flows must stay fixed.

Found by a real-browser click-through of every screen (v7.1.7.1 audit):
  * the Contact Skillvaya form called submitPlatformContact(), which was never defined;
  * 'Become a Provider' wrote to an element (#providerOptInMsg) that no longer exists, so the flow
    threw after the server had already upgraded the account;
  * Android 16 (targetSdk 36) no longer calls onBackPressed(), so the back gesture needs a callback.
These are static contract checks; they do not replace on-device testing.
"""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
COPIES = {
    "server app.py": (ROOT / "app.py").read_text(encoding="utf-8"),
    "android app.py": (ROOT / "android-native/app/src/main/python/app.py").read_text(encoding="utf-8"),
}
ACTIVITY = (ROOT / "android-native/app/src/main/java/za/co/skillvaya/app/MainActivity.java").read_text(encoding="utf-8")
BUILTINS = set(
    "if return function alert confirm prompt parseInt parseFloat encodeURIComponent decodeURIComponent String Number Boolean "
    "setTimeout setInterval event this document window JSON Math Date Array Object history location navigator console fetch open "
    "close isNaN typeof catch new select toggle add".split()
)


def defined_names(src):
    names = set(re.findall(r"function\s+([A-Za-z_$][\w$]*)\s*\(", src))
    names |= set(re.findall(r"(?:^|[;\s,(])(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=", src))
    names |= set(re.findall(r"(?:window\.|self\.)([A-Za-z_$][\w$]*)\s*=", src))
    names |= set(re.findall(r"\b([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?(?:function|\()", src))
    return names


def handler_names(src):
    used = set()
    for m in re.finditer(r"""\bon(?:click|change|input|submit|keyup|keydown)\s*=\s*\\?["']([^"'\\]*)""", src):
        used |= set(re.findall(r"(?<![\w$.])([A-Za-z_$][\w$]*)\s*\(", m.group(1)))
    return used


class ButtonWiringContract(unittest.TestCase):
    def test_every_inline_handler_function_is_defined_in_both_runtime_copies(self):
        for label, src in COPIES.items():
            missing = sorted(n for n in handler_names(src) - defined_names(src) if n not in BUILTINS)
            self.assertEqual(missing, [], "%s wires buttons to functions that do not exist: %s" % (label, missing))

    def test_contact_form_submit_handler_exists_and_opens_email(self):
        for label, src in COPIES.items():
            self.assertIn('onsubmit="submitPlatformContact(event)"', src, label)
            self.assertIn("function submitPlatformContact(e){", src, label)
            self.assertIn("window.location.href='mailto:skillvaya@gmail.com?subject='", src, label)
            self.assertIn("if(e&&e.preventDefault)e.preventDefault();", src, label)

    def test_msg_helper_survives_a_missing_element(self):
        for label, src in COPIES.items():
            self.assertIn("function msg(id,text,good=false){let el=document.getElementById(id);if(!el)return;", src, label)

    def test_become_provider_does_not_depend_on_removed_elements(self):
        for label, src in COPIES.items():
            start = src.index("async function becomeServiceProvider(){")
            body = src[start: src.index("\n", start)]
            self.assertNotIn("msg('providerOptInMsg'", body, label)
            self.assertIn("providerOptInNotice(", body, label)
            self.assertIn("document.getElementById('providerProfileNotice')", src, label)
            self.assertIn('id="providerProfileNotice"', src, label)

    def test_android_back_gesture_is_handled_for_sdk_36(self):
        self.assertIn("registerOnBackInvokedCallback", ACTIVITY)
        self.assertIn("webView.canGoBack()", ACTIVITY)
        self.assertIn("onBackPressed", ACTIVITY, "legacy path must remain for Android 12 and older")


if __name__ == "__main__":
    unittest.main()
