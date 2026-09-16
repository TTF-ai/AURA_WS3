"""
AURA Voice Node — Main ROS 2 node for voice interaction.

Pipeline:
    Microphone → VAD → STT → LLM Intent → Router → TTS → Speaker

Subscribes to:
    /auth/status
    /behavior/state (optional context)

Publishes:
    /voice/transcript
    /voice/intent
    /voice/response
    /voice/status
"""

import os
import re
import time
import json
import threading
import numpy as np
from dotenv import load_dotenv

load_dotenv(os.path.expanduser("~/.env"))

import rclpy
from rclpy.node import Node
from std_msgs.msg import String

from aura_face_msgs.msg import AuthenticationStatus
from aura_voice_msgs.msg import Transcript, VoiceIntent, VoiceStatus

from .audio_capture import AudioCapture
from .vad import VAD
from .language_manager import LanguageManager
from .intent_router import IntentRouter
from .audio_player import AudioPlayer
from .providers import create_stt_provider, create_llm_provider, create_tts_provider


class VoiceNode(Node):
    """Main AURA voice interaction node."""

    def __init__(self):
        super().__init__("voice_node")

        # -------------------------------------------------------
        # Parameters
        # -------------------------------------------------------
        self.declare_parameter("stt_provider", "groq")
        self.declare_parameter("stt_model", "whisper-large-v3-turbo")
        self.declare_parameter("llm_provider", "groq")
        self.declare_parameter("llm_model", "openai/gpt-oss-20b")
        self.declare_parameter("tts_provider", "edge")
        self.declare_parameter("tts_voice", "")
        self.declare_parameter("default_language", "en")
        self.declare_parameter("stt_timeout_seconds", 10.0)
        self.declare_parameter("llm_timeout_seconds", 10.0)
        self.declare_parameter("tts_timeout_seconds", 10.0)
        self.declare_parameter("max_recording_seconds", 10.0)
        self.declare_parameter("vad_energy_threshold", 0.01)
        self.declare_parameter("wake_word", "aura")
        self.declare_parameter("wake_word_min_duration_ms", 250.0)
        self.declare_parameter("input_mode", "speech")
        self.declare_parameter("debug_audio_logging", False)

        # -------------------------------------------------------
        # State
        # -------------------------------------------------------
        self.authenticated = False
        self.auth_username = ""
        self.last_auth_state = False
        self.current_behavior = "UNKNOWN"
        self.follow_state = "IDLE"
        self.voice_status = "IDLE"
        self.input_mode = self.get_parameter("input_mode").value.lower()
        self._processing = False

        # -------------------------------------------------------
        # Language Manager
        # -------------------------------------------------------
        self.language_manager = LanguageManager()

        # -------------------------------------------------------
        # Providers
        # -------------------------------------------------------
        stt_name = self.get_parameter("stt_provider").value
        llm_name = self.get_parameter("llm_provider").value
        tts_name = self.get_parameter("tts_provider").value

        stt_timeout = self.get_parameter("stt_timeout_seconds").value
        llm_timeout = self.get_parameter("llm_timeout_seconds").value
        tts_timeout = self.get_parameter("tts_timeout_seconds").value

        self.stt = create_stt_provider(
            stt_name,
            model=self.get_parameter("stt_model").value,
            timeout=stt_timeout,
        )
        self.llm = create_llm_provider(
            llm_name,
            model=self.get_parameter("llm_model").value,
            timeout=llm_timeout,
        )
        self.tts = create_tts_provider(
            tts_name,
            timeout=tts_timeout,
        )

        # -------------------------------------------------------
        # Audio
        # -------------------------------------------------------
        self.audio_capture = AudioCapture()
        self.vad = VAD(
            energy_threshold=self.get_parameter("vad_energy_threshold").value,
            max_speech_ms=int(self.get_parameter("max_recording_seconds").value * 1000),
        )
        self.audio_player = AudioPlayer()

        # -------------------------------------------------------
        # Intent Router
        # -------------------------------------------------------
        self.intent_router = IntentRouter(self, self.language_manager)

        # -------------------------------------------------------
        # Publishers
        # -------------------------------------------------------
        self.transcript_pub = self.create_publisher(Transcript, "/voice/transcript", 10)
        self.intent_pub = self.create_publisher(VoiceIntent, "/voice/intent", 10)
        self.response_pub = self.create_publisher(String, "/voice/response", 10)
        self.status_pub = self.create_publisher(VoiceStatus, "/voice/status", 10)

        # -------------------------------------------------------
        # Subscribers
        # -------------------------------------------------------
        self.text_sub = self.create_subscription(
            String, "/voice/text_input", self.text_input_callback, 10
        )
        self.auth_sub = self.create_subscription(
            AuthenticationStatus, "/auth/status", self.auth_callback, 10
        )

        # Optional: behavior context
        try:
            from aura_behavior_msgs.msg import BehaviorState
            self.behavior_sub = self.create_subscription(
                BehaviorState, "/behavior/state", self.behavior_callback, 10
            )
        except ImportError:
            self.get_logger().info("aura_behavior_msgs not available, skipping behavior context")

        # -------------------------------------------------------
        # Startup validation
        # -------------------------------------------------------
        self._validate_startup()

        # -------------------------------------------------------
        # Audio processing thread
        # -------------------------------------------------------
        self._running = True
        if self.input_mode == "speech":
            self._audio_thread = threading.Thread(target=self._audio_loop, daemon=True)
            self._audio_thread.start()
            self.get_logger().info("Voice Node started in SPEECH mode.")
        else:
            self.get_logger().info(f"Voice Node started in TEXT mode (input_mode={self.input_mode}).")
            self._publish_status("IDLE", "Text input mode enabled")

    # =============================================================
    # STARTUP VALIDATION
    # =============================================================

    def _validate_startup(self):
        """Check API keys and hardware at startup."""
        issues = []

        if not self.stt.is_available():
            issues.append("STT: GROQ_API_KEY not set")
        if not self.llm.is_available():
            issues.append("LLM: API key not set")
        if not self.tts.is_available():
            issues.append(f"TTS: API key not set for {self.get_parameter('tts_provider').value}")

        if issues:
            for issue in issues:
                self.get_logger().warning(f"⚠ {issue}")
        else:
            stt_name = self.get_parameter("stt_provider").value
            llm_name = self.get_parameter("llm_provider").value
            tts_name = self.get_parameter("tts_provider").value
            self.get_logger().info(
                f"VOICE SYSTEM READY | STT: {stt_name} | LLM: {llm_name} | TTS: {tts_name}"
            )

        if not self.audio_player.is_available():
            self.get_logger().warning("⚠ No audio player detected (aplay/paplay/ffplay)")

        self._publish_status("IDLE", "Startup complete")

    # =============================================================
    # CALLBACKS
    # =============================================================

    def auth_callback(self, msg):
        previous_state = self.authenticated
        self.authenticated = msg.authenticated
        self.auth_username = msg.username if msg.authenticated else ""

        if msg.authenticated and not previous_state:
            preferred_lang = self.language_manager.get_language(self.auth_username)
            self.get_logger().info(
                f"User authenticated: {self.auth_username}; speaking confirmation"
            )
            threading.Thread(
                target=self._speak,
                args=(
                    f"Hi {self.auth_username}, How can I help you today?",
                    preferred_lang,
                ),
                daemon=True,
            ).start()

    def behavior_callback(self, msg):
        self.current_behavior = msg.behavior

    def text_input_callback(self, msg):
        """Handle a text-driven command for testing without microphone input."""
        if self.input_mode != "text":
            return
        if self._processing:
            return

        text = (msg.data or "").strip()
        if not text:
            return

        self.get_logger().info(f"Text input received: \"{text}\"")
        self._processing = True
        try:
            self._execute_command(text, "en", source="text")
        finally:
            self._processing = False

    # =============================================================
    # AUDIO PROCESSING LOOP (background thread)
    # =============================================================

    def _audio_loop(self):
        """Continuously capture audio, detect speech, and process."""
        try:
            self.audio_capture.start()
            self.get_logger().info("Microphone stream started")
        except Exception as e:
            self.get_logger().error(f"Failed to open microphone: {e}")
            self._publish_status("ERROR", f"Microphone error: {e}")
            return

        while self._running:
            try:
                frame = self.audio_capture.read_frame()
                speech_pcm = self.vad.process_frame(frame)

                if speech_pcm is not None and not self._processing:
                    self._processing = True
                    # Process in a separate thread to not block audio capture
                    threading.Thread(
                        target=self._process_speech,
                        args=(speech_pcm,),
                        daemon=True,
                    ).start()

            except Exception as e:
                self.get_logger().error(f"Audio capture error: {e}")
                time.sleep(0.1)

        self.audio_capture.stop()

    # =============================================================
    # SPEECH PROCESSING PIPELINE
    # =============================================================

    def _is_wake_word_command(self, text: str) -> bool:
        """Lightweight wake-word gate for the command phrase.

        This is intentionally a post-VAD gate: the microphone pipeline must
        first observe speech activity, and only then do we allow command
        processing if the detected phrase begins with the wake word.
        """
        if not text:
            return False

        normalized = re.sub(r'[^a-z0-9\s]', ' ', text.lower()).strip()
        normalized = re.sub(r'\s+', ' ', normalized)
        wake_word = self.get_parameter("wake_word").value.lower()
        return re.search(rf"(^|\s){re.escape(wake_word)}(\s|$)", normalized) is not None

    def _audio_has_wake_word_candidate(self, pcm_bytes: bytes) -> bool:
        """Before Whisper, do a lightweight speech gate.

        This does not replace a dedicated hotword model; it ensures only
        speech segments with sufficient energy and duration are sent onward.
        """
        if not pcm_bytes:
            return False

        raw = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32)
        if raw.size == 0:
            return False

        energy = np.abs(raw) / 32768.0
        rms = float(np.sqrt(np.mean(np.square(energy))))
        length_ms = (len(raw) / 16000.0) * 1000.0
        min_duration_ms = float(self.get_parameter("wake_word_min_duration_ms").value)

        # A short, speech-like segment is required before STT/LLM is allowed.
        return rms > 0.02 and length_ms >= min_duration_ms

    @staticmethod
    def _normalize_language_tag(language: str) -> str:
        """Use a single spoken language instead of mixed tags such as en+kn."""
        if not language:
            return "en"
        normalized = str(language).strip().lower().replace("_", "-")
        if "+" in normalized:
            return normalized.split("+", 1)[-1].strip() or "en"
        if "-" in normalized:
            return normalized.split("-", 1)[0] or "en"
        return normalized

    def _extract_send_message_request(self, text: str):
        """Extract a user-authored Telegram message request from spoken text."""
        if not text:
            return None

        lowered = text.lower().strip()
        patterns = [
            "send message",
            "send a message",
            "send this message",
            "send to telegram",
            "send this to telegram",
            "send this to group",
            "send this to family",
            "send to family",
            "post to telegram",
            "post to group",
            "tell the group",
            "share this",
            "send it to telegram",
            "send message to telegram",
            "message bhejo",
            "message send karo",
            "message send kardo",
            "message send maadi",
            "message send cheyyu",
            "message send chey",
            "message kodo",
            "message send",
        ]

        match = None
        match_idx = -1
        for pattern in patterns:
            idx = lowered.find(pattern)
            if idx != -1 and (match_idx == -1 or idx < match_idx):
                match = pattern
                match_idx = idx

        if not match:
            return None

        payload = text[match_idx + len(match):].strip()
        if payload.startswith(":"):
            payload = payload[1:].strip()
        if payload.startswith("-"):
            payload = payload[1:].strip()

        if payload and payload.lower() in ["to", "group", "family", "telegram", "telegram group", "family group"]:
            payload = ""

        include_photo = any(
            token in lowered
            for token in [
                "photo",
                "camera",
                "picture",
                "image",
                "snapshot",
                "pic",
                "photo lo",
                "image lo",
            ]
        )

        if not payload:
            payload = text

        if payload.lower().startswith("please "):
            payload = payload[5:].strip()

        cleaned = re.sub(r'^(to|telegram|group|family|please|plz)\s+', '', payload, flags=re.I)
        cleaned = cleaned.strip()

        return {"message": cleaned if cleaned else payload.strip(), "include_photo": include_photo}

    def _detect_language_change_request(self, text: str):
        """Return a language code if the user is asking to switch speaking language."""
        if not text:
            return None

        lowered = re.sub(r"[^a-z\s]", " ", text.lower())
        lowered = re.sub(r"\s+", " ", lowered).strip()

        language_map = {
            "english": "en",
            "en": "en",
            "kannada": "kn",
            "kn": "kn",
            "kanglish": "kn",
            "hindi": "hi",
            "hi": "hi",
            "hinglish": "hi",
            "telugu": "te",
            "te": "te",
            "teluglish": "te",
            "tamil": "ta",
            "ta": "ta",
            "tanglish": "ta",
            "malayalam": "ml",
            "ml": "ml",
            "manglish": "ml",
            "marathi": "mr",
            "mr": "mr",
            "gujarati": "gu",
            "gu": "gu",
            "bengali": "bn",
            "bn": "bn",
        }

        patterns = [
            "speak in ", "talk in ", "talk in english", "talk in kannada", "talk in telugu",
            "speak telugu", "speak in telugu", "speak in kannada", "speak in hindi",
            "switch to ", "change language to ", "change to ", "use ",
            "lets talk in ", "let's talk in ", "let us talk in ", "speak english",
            "speak kannada", "speak hindi", "speak telugu",
            "speak in hinglish", "talk in hinglish", "speak in kanglish", "talk in kanglish",
            "speak in teluglish", "talk in teluglish", "speak in tanglish", "talk in tanglish",
            "speak in manglish", "talk in manglish",
        ]

        for phrase in patterns:
            if phrase in lowered:
                for name, code in language_map.items():
                    if f"{phrase}{name}" in lowered or phrase.endswith(name) and phrase in lowered:
                        return code

        for name, code in language_map.items():
            if re.search(rf"\b{name}\b", lowered):
                if any(token in lowered for token in ["speak", "talk", "language", "switch", "change", "use", "lets", "let's", "let us"]):
                    return code

        return None

    def _execute_command(self, text: str, detected_lang: str = "en", source: str = "speech"):
        """Run the LLM + router path for both audio and text inputs."""
        total_start = time.time()

        if self.authenticated:
            requested_lang = self._detect_language_change_request(text)
            if requested_lang:
                previous_lang = self.language_manager.get_language(self.auth_username)
                ok = self.language_manager.set_language(self.auth_username, requested_lang)
                if ok:
                    self.get_logger().info(
                        f"Language switched for {self.auth_username}: {requested_lang} (was {previous_lang})"
                    )
                    msg = String()
                    lang_name = {
                        "en": "English",
                        "kn": "Kannada",
                        "hi": "Hindi",
                        "te": "Telugu",
                        "ta": "Tamil",
                        "ml": "Malayalam",
                        "mr": "Marathi",
                        "gu": "Gujarati",
                        "bn": "Bengali",
                    }.get(requested_lang, requested_lang.upper())
                    response_text = f"Okay, I will speak in {lang_name}."
                    self.response_pub.publish(String(data=response_text))
                    self._speak(response_text, requested_lang)
                    self._publish_status("IDLE", f"Language set to {requested_lang}")
                    return

        if source == "speech" and not self._is_wake_word_command(text):
            self.get_logger().info(
                f"Wake-word gate rejected background speech: \"{text}\""
            )
            self._publish_status("IDLE", "Background speech ignored")
            return

        self.get_logger().info(f"{source.upper()} input: \"{text}\" [lang={detected_lang}]")

        t_msg = Transcript()
        t_msg.header.stamp = self.get_clock().now().to_msg()
        t_msg.text = text
        t_msg.language = detected_lang
        t_msg.confidence = 1.0 if source == "text" else 0.9
        self.transcript_pub.publish(t_msg)

        if not self.authenticated:
            self.get_logger().warning("Voice command received but no user authenticated")
            self._speak("Please authenticate first.", "en")
            self._publish_status("IDLE", "Not authenticated")
            return

        preferred_lang = self._normalize_language_tag(
            self.language_manager.get_language(self.auth_username)
        )

        send_request = self._extract_send_message_request(text)
        if send_request:
            intent = "SEND_MESSAGE"
            parameters = {
                "message": send_request["message"],
                "include_photo": send_request["include_photo"],
            }
            response_text = "Sending your message to the family group."
            if preferred_lang.startswith("kn"):
                response_text = "ನಿಮ್ಮ ಸಂದೇಶವನ್ನು ಕುಟುಂಬ ಗುಂಪಿಗೆ ಕಳಿಸುತ್ತೇನೆ."
            llm_latency = 0.0
        else:
            self._publish_status("THINKING", "Extracting intent...")
            llm_start = time.time()
            context = {
                "authenticated": True,
                "username": self.auth_username,
                "preferred_language": preferred_lang,
                "follow_state": self.follow_state,
                "behavior": self.current_behavior,
            }

            intent_result = self.llm.generate_intent(text, context=context)
            llm_latency = time.time() - llm_start

            intent = intent_result.get("intent", "UNKNOWN")
            parameters = intent_result.get("parameters", {})
            response_text = intent_result.get("response_text", "")

        if intent == "UNKNOWN":
            lowered = text.lower()
            if any(k in lowered for k in ["hello", "hi", "hey", "namaskara", "namaste"]):
                intent = "HELP"
                response_text = "Hello! How can I help you?" if preferred_lang.startswith("en") else "ನಮಸ್ಕಾರ! ನಾನು ನಿಮಗೆ ಹೇಗೆ ಸಹಾಯ ಮಾಡಬಹುದು?"
            elif any(k in lowered for k in ["what can you do", "what are you capable", "capable", "help me", "can you help"]):
                intent = "HELP"
                response_text = "I can assist with follow, information, and status."
                if preferred_lang.startswith("kn"):
                    response_text = "ನಾನು ಫಾಲೋ, ಮಾಹಿತಿ ಮತ್ತು ಸ್ಥಿತಿಯನ್ನು ಸಹಾಯ ಮಾಡಬಹುದು."
            elif any(k in lowered for k in ["what is your name", "your name", "who are you"]):
                intent = "HELP"
                response_text = "I am AURA."
                if preferred_lang.startswith("kn"):
                    response_text = "ನಾನು AURA."
            elif any(k in lowered for k in ["what are you seeing", "what do you see", "seeing"]):
                intent = "HELP"
                response_text = "I can see the room and you."
                if preferred_lang.startswith("kn"):
                    response_text = "ನಾನು room ಮತ್ತು ನಿಮಗೆ ನೋಡುತ್ತೇನೆ."
            elif any(k in lowered for k in ["what is my name", "who am i", "my name"]):
                intent = "WHO_AM_I"
                response_text = f"Your name is {self.auth_username}."
                if preferred_lang.startswith("kn"):
                    response_text = f"ನಿಮ್ಮ ಹೆಸರು {self.auth_username}."

        self.get_logger().info(
            f"LLM ({llm_latency:.2f}s): intent={intent} | response=\"{response_text}\""
        )

        i_msg = VoiceIntent()
        i_msg.header.stamp = self.get_clock().now().to_msg()
        i_msg.intent = intent
        i_msg.parameters_json = json.dumps(parameters)
        i_msg.response_text = response_text
        i_msg.language = preferred_lang
        self.intent_pub.publish(i_msg)

        exec_result = self.intent_router.execute(intent, parameters, self.auth_username)
        self.get_logger().info(f"Intent executed: {exec_result}")

        if intent == "CHANGE_LANGUAGE" and exec_result.startswith("language_changed"):
            preferred_lang = parameters.get("language", preferred_lang)

        if response_text:
            r_msg = String()
            r_msg.data = response_text
            self.response_pub.publish(r_msg)
            self._speak(response_text, preferred_lang)

        total_latency = time.time() - total_start
        self.get_logger().info(
            f"Pipeline complete ({total_latency:.2f}s): "
            f"source={source} LLM={llm_latency:.2f}s"
        )
        self._publish_status("IDLE", f"Complete in {total_latency:.1f}s")

    def _process_speech(self, pcm_bytes: bytes):
        """Full pipeline: speech gate → STT → LLM → Router → TTS."""
        total_start = time.time()

        if not self._audio_has_wake_word_candidate(pcm_bytes):
            self.get_logger().info("Wake-word candidate rejected before Whisper: low-energy/noisy segment")
            self._publish_status("IDLE", "Wake-word candidate rejected")
            return

        try:
            self._publish_status("TRANSCRIBING", "Processing speech...")
            stt_start = time.time()

            wav_bytes = AudioCapture.pcm_to_wav(pcm_bytes)
            result = self.stt.transcribe(wav_bytes)

            stt_latency = time.time() - stt_start
            text = result.get("text", "").strip()
            detected_lang = result.get("language", "unknown")

            if not text:
                self.get_logger().info("Empty transcription, ignoring")
                self._publish_status("IDLE", "Empty transcript")
                return

            if not self._is_wake_word_command(text):
                self.get_logger().info(
                    f"Wake-word gate rejected background speech: \"{text}\""
                )
                self._publish_status("IDLE", "Background speech ignored")
                return

            self.get_logger().info(
                f"STT ({stt_latency:.2f}s): \"{text}\" [lang={detected_lang}]"
            )
            self._execute_command(text, detected_lang, source="speech")

        except Exception as e:
            self.get_logger().error(f"Voice pipeline error: {e}")
            self._publish_status("ERROR", str(e))

        finally:
            self._processing = False

    # =============================================================
    # TTS + PLAYBACK
    # =============================================================

    def _speak(self, text: str, language: str):
        """Synthesize and play speech."""
        self._publish_status("SPEAKING", text[:50])

        tts_start = time.time()

        try:
            provider = self.tts
            audio_format = "mp3"  # EdgeTTS streams MP3

            normalized_language = language.lower().replace("_", "-")
            if not provider.supports_language(normalized_language):
                self.get_logger().warning(
                    f"No TTS provider supports language '{language}', falling back to 'en'"
                )
                normalized_language = "en"

            audio_bytes = provider.synthesize(text, language=normalized_language)

            tts_latency = time.time() - tts_start
            self.get_logger().info(f"TTS ({tts_latency:.2f}s): {len(audio_bytes)} bytes")

            self.audio_player.play(audio_bytes, audio_format=audio_format)

        except Exception as e:
            self.get_logger().error(f"TTS/playback error: {e}")

    # =============================================================
    # STATUS PUBLISHING
    # =============================================================

    def _publish_status(self, status: str, detail: str = ""):
        """Publish voice system status."""
        self.voice_status = status
        msg = VoiceStatus()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.status = status
        msg.detail = detail
        self.status_pub.publish(msg)

    # =============================================================
    # SHUTDOWN
    # =============================================================

    def destroy_node(self):
        self._running = False
        self.audio_capture.stop()
        super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = VoiceNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
