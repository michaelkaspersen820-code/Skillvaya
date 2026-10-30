"""Regression guard for SV77-CALL-MEDIA-01: the answering phone must reuse the offer's transceivers,
otherwise its SDP answer is receive-only and the caller hears/sees nothing (one-way calls)."""
import pathlib, re, unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
COPIES = [ROOT / "app.py", ROOT / "android-native" / "app" / "src" / "main" / "python" / "app.py"]


class CallMediaDirectionContract(unittest.TestCase):
    def check(self, src):
        peer = src[src.index("async function svCreatePeer("):src.index("function svBindAnswerSenders(")]
        # No transceiver may be created in svCreatePeer before the caller-only guard.
        before_guard = peer[:peer.index("if(call.isCaller){")]
        self.assertNotIn("pc.addTransceiver(", before_guard)
        self.assertIn("pc.addTransceiver(", peer[peer.index("if(call.isCaller){"):])
        self.assertIn("function svBindAnswerSenders(call)", src)
        accept = src[src.index("async function acceptSkillvayaVideoCall("):]
        accept = accept[:accept.index("createAnswer()")]
        i_remote = accept.index("setRemoteDescription(")
        i_bind = accept.index("svBindAnswerSenders(call)")
        i_attach = accept.index("svAttachCallMedia(call,")
        self.assertTrue(i_remote < i_bind < i_attach, "answer senders must be bound after the offer and before media is attached")
        self.assertRegex(src, r"ta\.direction='sendrecv'")

    def test_both_copies(self):
        for p in COPIES:
            with self.subTest(copy=str(p)):
                self.check(p.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
