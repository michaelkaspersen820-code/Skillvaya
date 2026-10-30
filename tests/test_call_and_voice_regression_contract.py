from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
RUNTIMES = [ROOT / "app.py", ROOT / "android-native" / "app" / "src" / "main" / "python" / "app.py"]
JAVA = ROOT / "android-native" / "app" / "src" / "main" / "java" / "za" / "co" / "skillvaya" / "app" / "MainActivity.java"

class CallAndVoiceRegressionContract(unittest.TestCase):
    def test_chat_has_separate_in_app_voice_and_video_buttons(self):
        for path in RUNTIMES:
            source = path.read_text(encoding="utf-8")
            start = source.index("function ensureSkillvayaChatMediaToolbar(")
            end = source.index("\nfunction svReadFileAsDataUrl", start)
            toolbar = source[start:end]
            self.assertIn("textContent='Call'", toolbar)
            self.assertIn("textContent='Video call'", toolbar)
            self.assertIn("startSkillvayaVideoCall(businessId,customerId,'voice')", toolbar)
            self.assertIn("startSkillvayaVideoCall(businessId,customerId,'video')", toolbar)
            self.assertIn("href='tel:'+normalizedPhone", toolbar)

    def test_recipient_attaches_media_before_sending_answer(self):
        for path in RUNTIMES:
            source = path.read_text(encoding="utf-8")
            start = source.index("async function acceptSkillvayaVideoCall()")
            end = source.index("\nasync function declineSkillvayaVideoCall()", start)
            accept = source[start:end]
            self.assertLess(accept.index("svActiveVideoCall=call"), accept.index("await svAttachCallMedia(call,mediaResult.stream)"))
            self.assertLess(accept.index("await svAttachCallMedia(call,mediaResult.stream)"), accept.index("call.pc.createAnswer()"))
            self.assertLess(accept.index("call.pc.createAnswer()"), accept.index("action:'accept'"))
            self.assertIn("const mode=incoming.media_type==='voice'?'voice':'video';", accept)

    def test_voice_and_video_media_are_negotiated_separately(self):
        for path in RUNTIMES:
            source = path.read_text(encoding="utf-8")
            self.assertIn("call.videoSender=call.mediaMode==='video'?", source)
            self.assertIn("if(call.videoSender)replacements.push", source)
            self.assertIn("CASE WHEN vc.offer_sdp LIKE '%%m=video%%' THEN 'video' ELSE 'voice' END AS media_type", source)
            self.assertIn("sv-call-voice-only", source)

    def test_android_voice_recognition_is_prepared_and_kept_until_manual_stop(self):
        source = JAVA.read_text(encoding="utf-8")
        self.assertIn("private void prepareNativeVoiceRecognizer()", source)
        stop = source[source.index("private void stopNativeVoice"):source.index("private void scheduleNativeVoiceRestart")]
        self.assertIn("nativeSpeechRecognizer.stopListening()", stop)
        self.assertNotIn("nativeSpeechRecognizer.cancel()", stop)
        self.assertIn("prepareNativeVoiceRecognizer();", source)
        self.assertIn("nativeVoiceStopRequested", source)
        self.assertIn("window.svNativeVoiceResult", source)
        self.assertIn("window.svNativeVoiceFlushInterim", source)
        self.assertIn("EXTRA_SPEECH_INPUT_COMPLETE_SILENCE_LENGTH_MILLIS, 60000L", source)
        self.assertIn("EXTRA_SPEECH_INPUT_POSSIBLY_COMPLETE_SILENCE_LENGTH_MILLIS, 30000L", source)
        self.assertIn("prepareNativeVoiceRecognizer();\n                                PushTokenRegistrar.register", source)


    def test_customer_call_inbox_includes_calls_addressed_to_callee(self):
        for path in RUNTIMES:
            source = path.read_text(encoding="utf-8")
            self.assertIn("WHERE (vc.callee_id=? OR vc.customer_id=?) AND vc.status IN ('ringing','accepted')", source)

    def test_end_call_waits_for_server_confirmation(self):
        for path in RUNTIMES:
            source = path.read_text(encoding="utf-8")
            start = source.index("async function closeSkillvayaVideoCall(sendEnd)")
            end = source.index("\nfunction toggleSkillvayaCallMic", start)
            close = source[start:end]
            self.assertIn("api(", close)
            self.assertNotIn("await api(", close)
            self.assertIn("Tear down the local call immediately", close)
            self.assertIn("action:'end'", close)
            self.assertIn("The server did not confirm that the call ended.", close)
if __name__ == "__main__":
    unittest.main()
