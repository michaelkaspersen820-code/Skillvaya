from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
SOURCES = [
    ROOT / "app.py",
    ROOT / "android-native" / "app" / "src" / "main" / "python" / "app.py",
]

class MessageNavigationAndDeliveryContract(unittest.TestCase):
    def read(self, path):
        return path.read_text(encoding="utf-8")

    def test_both_runtime_copies_have_navigation_generation_guard(self):
        for path in SOURCES:
            with self.subTest(path=str(path)):
                source = self.read(path)
                self.assertIn("let svMessagesNavigationVersion=0,svMessagePollInitialized=false;", source)
                self.assertIn("const navVersion=++svMessagesNavigationVersion;", source)
                self.assertIn("if(navVersion!==svMessagesNavigationVersion||document.body.classList.contains('messages-conversation-open'))return;", source)

    def test_opening_a_chat_fetches_fresh_messages_not_stale_cache(self):
        for path in SOURCES:
            with self.subTest(path=str(path)):
                source = self.read(path)
                start = source.index("async function openMessageConversation(")
                end = source.index("\nasync function sendConversationReply(", start)
                function = source[start:end]
                # cold path always asks the server; the warm path (inbox loaded < 2 min ago) must re-check the server in the background
                self.assertIn("await api('/api/messages')", function)
                self.assertIn("window.svMessagesItems.at<120000", function)
                self.assertIn("if(svWarm){api('/api/messages').then(fresh=>", function)
                self.assertNotIn("sessionStorage.getItem(svMessageCacheKey())", function)
                self.assertIn("svLastKnownMessageIds=new Set(items.map(m=>String(m.id)))", function)

    def test_inbox_refreshes_when_new_incoming_message_arrives(self):
        for path in SOURCES:
            with self.subTest(path=str(path)):
                source = self.read(path)
                start = source.index("async function svPollMessageNotifications()")
                end = source.index("\nfunction svStartMessageLiveUpdates()", start)
                function = source[start:end]
                self.assertIn("hasNewIncoming", function)
                self.assertIn("svMessagePollInitialized&&items.some", function)
                self.assertIn("svMessagePollInitialized=true", function)
                self.assertIn("await loadMessageThreads()", function)

    def test_chat_exposes_normal_phone_call_without_removing_video_call(self):
        for path in SOURCES:
            with self.subTest(path=str(path)):
                source = self.read(path)
                start = source.index("function ensureSkillvayaChatMediaToolbar(")
                end = source.index("\nfunction svReadFileAsDataUrl", start)
                function = source[start:end]
                self.assertIn("href='tel:'+normalizedPhone", function)
                self.assertIn("startSkillvayaVideoCall(businessId,customerId,", function)
                self.assertIn("'voice'", function)
                self.assertIn("'video'", function)
                self.assertIn("phoneDigits.length>=7", function)

    def test_authenticated_conversation_data_contains_contact_phone_fields(self):
        for path in SOURCES:
            with self.subTest(path=str(path)):
                source = self.read(path)
                self.assertIn("b.phone business_phone", source)
                self.assertIn("cu.phone customer_phone", source)

    def test_notification_bell_is_home_header_only_in_both_runtime_copies(self):
        for path in SOURCES:
            with self.subTest(path=str(path)):
                source = self.read(path)
                self.assertEqual(source.count('id="svNotificationBell"'), 1)
                self.assertIn('<header class="top"><div class="wrap nav">', source)
                self.assertIn('id="svNotificationBell" class="sv-notification-bell"', source)
                self.assertIn('.sv-notification-bell{-webkit-appearance:none;', source)
                self.assertIn('.sv-notification-bell:focus,.sv-notification-bell:focus-visible,.sv-notification-bell:active{background:#fff!important;', source)
                self.assertIn("const b=document.getElementById('svNotificationBell');if(!b)return null;", source)
                self.assertNotIn("document.body.appendChild(b)", source)
                self.assertIn("api('/api/notifications')", source)
                handler_start = source.index('function svEnsureNotificationBell()')
                handler_end = source.index('function svSetNotificationCount', handler_start)
                handler = source[handler_start:handler_end]
                self.assertLess(handler.index('showMessagesScreen(true)'), handler.index("api('/api/notifications')"))
                self.assertIn("addEventListener('click',()=>{", handler)


    def test_home_notification_bell_shows_immediately_after_session_restore(self):
        for path in SOURCES:
            with self.subTest(path=str(path)):
                source = self.read(path)
                start = source.index("async function sessionInfo(knownUser=null)")
                end = source.index("\nasync function saveProfilePhoto()", start)
                function = source[start:end]
                self.assertIn("me=d.user;const bell=svEnsureNotificationBell();if(bell)bell.classList.toggle('is-visible',!!me);", function)


if __name__ == "__main__":
    unittest.main()

