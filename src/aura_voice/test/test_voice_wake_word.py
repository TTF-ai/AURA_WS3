import unittest

from aura_voice.voice_node import VoiceNode


class WakeWordGateTests(unittest.TestCase):
    def setUp(self):
        self.node = VoiceNode.__new__(VoiceNode)

        self.node.require_wake_word = False

        def fake_get_parameter(name):
            values = {
                "wake_word": "aura",
                "require_wake_word": False,
            }
            return type("Param", (), {"value": values.get(name, "")})()

        self.node.get_parameter = fake_get_parameter

    def test_command_without_wake_word_is_allowed_when_gate_is_disabled(self):
        self.assertTrue(self.node._is_wake_word_command("hello how are you"))

    def test_command_with_wake_word_still_works(self):
        self.assertTrue(self.node._is_wake_word_command("aura hello there"))


if __name__ == "__main__":
    unittest.main()
