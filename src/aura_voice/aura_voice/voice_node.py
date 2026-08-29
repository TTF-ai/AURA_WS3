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
import time
import json
import threading
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
        self.declare_parameter("debug_audio_logging", False)

        # -------------------------------------------------------
        # State
        # -------------------------------------------------------
        self.authenticated = False
        self.auth_username = ""
        self.current_behavior = "UNKNOWN"
        self.follow_state = "IDLE"
        self.voice_status = "IDLE"
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
        self._audio_thread = threading.Thread(target=self._audio_loop, daemon=True)
        self._audio_thread.start()

        self.get_logger().info("Voice Node started and listening.")

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
        self.authenticated = msg.authenticated
        self.auth_username = msg.username if msg.authenticated else ""

    def behavior_callback(self, msg):
        self.current_behavior = msg.behavior

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

    def _process_speech(self, pcm_bytes: bytes):
        """Full pipeline: STT → LLM → Router → TTS."""
        total_start = time.time()

        try:
            # --- 1. STT ---
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

            self.get_logger().info(
                f"STT ({stt_latency:.2f}s): \"{text}\" [lang={detected_lang}]"
            )

            # Publish transcript
            t_msg = Transcript()
            t_msg.header.stamp = self.get_clock().now().to_msg()
            t_msg.text = text
            t_msg.language = detected_lang
            t_msg.confidence = result.get("confidence", 0.0)
            self.transcript_pub.publish(t_msg)

            # --- 2. Auth check ---
            if not self.authenticated:
                self.get_logger().warning("Voice command received but no user authenticated")
                self._speak("Please authenticate first.", "en")
                self._publish_status("IDLE", "Not authenticated")
                return

            # --- 3. LLM Intent ---
            self._publish_status("THINKING", "Extracting intent...")
            llm_start = time.time()

            preferred_lang = self.language_manager.get_language(self.auth_username)

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

            self.get_logger().info(
                f"LLM ({llm_latency:.2f}s): intent={intent} | response=\"{response_text}\""
            )

            # Publish intent
            i_msg = VoiceIntent()
            i_msg.header.stamp = self.get_clock().now().to_msg()
            i_msg.intent = intent
            i_msg.parameters_json = json.dumps(parameters)
            i_msg.response_text = response_text
            i_msg.language = preferred_lang
            self.intent_pub.publish(i_msg)

            # --- 4. Execute intent ---
            exec_result = self.intent_router.execute(intent, parameters, self.auth_username)
            self.get_logger().info(f"Intent executed: {exec_result}")

            # After language change, refresh preferred lang for TTS
            if intent == "CHANGE_LANGUAGE" and exec_result.startswith("language_changed"):
                preferred_lang = parameters.get("language", preferred_lang)

            # --- 5. TTS ---
            if response_text:
                # Publish text response
                r_msg = String()
                r_msg.data = response_text
                self.response_pub.publish(r_msg)

                self._speak(response_text, preferred_lang)

            total_latency = time.time() - total_start
            self.get_logger().info(
                f"Pipeline complete ({total_latency:.2f}s): "
                f"STT={stt_latency:.2f}s LLM={llm_latency:.2f}s"
            )

            self._publish_status("IDLE", f"Complete in {total_latency:.1f}s")

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

            if not provider.supports_language(language):
                self.get_logger().warning(
                    f"No TTS provider supports language '{language}', falling back to 'en'"
                )
                language = "en"

            audio_bytes = provider.synthesize(text, language=language)

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
