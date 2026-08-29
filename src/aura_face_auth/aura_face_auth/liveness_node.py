#!/usr/bin/env python3
"""
AURA Face Liveness Node

Anti-spoofing verification.
Subscribes to /face/crops (FaceCrop).
Publishes to /face/liveness (FaceLiveness).

Development mode defaults to is_live=false (fail-closed).
Production requires a real anti-spoofing model.
"""

import time

import cv2
import numpy as np

import rclpy
from rclpy.node import Node
from cv_bridge import CvBridge

from aura_face_msgs.msg import FaceCrop
from aura_face_msgs.msg import FaceLiveness


class LivenessNode(Node):

    def __init__(self):
        super().__init__("liveness_node")

        # ---------------------------------------------------------
        # ROS 2 parameters
        # ---------------------------------------------------------

        self.declare_parameter("liveness_threshold", 0.5)
        self.declare_parameter("liveness_interval", 0.5)
        self.declare_parameter("development_mode", False)
        self.declare_parameter("dev_liveness_score", 0.0)
        self.declare_parameter("model_path", "")

        self.liveness_threshold = self.get_parameter(
            "liveness_threshold"
        ).value

        self.liveness_interval = self.get_parameter(
            "liveness_interval"
        ).value

        self.development_mode = self.get_parameter(
            "development_mode"
        ).value

        self.dev_liveness_score = self.get_parameter(
            "dev_liveness_score"
        ).value

        self.model_path_param = self.get_parameter(
            "model_path"
        ).value

        # ---------------------------------------------------------
        # Publisher
        # ---------------------------------------------------------

        self.liveness_pub = self.create_publisher(
            FaceLiveness,
            "/face/liveness",
            10
        )

        # ---------------------------------------------------------
        # Subscriber
        # ---------------------------------------------------------

        self.crop_sub = self.create_subscription(
            FaceCrop,
            "/face/crops",
            self.crop_callback,
            10
        )

        # ---------------------------------------------------------
        # OpenCV bridge
        # ---------------------------------------------------------

        self.bridge = CvBridge()

        # ---------------------------------------------------------
        # Load liveness model
        # ---------------------------------------------------------

        self.liveness_model = None
        self._load_model()

        # ---------------------------------------------------------
        # Throttling
        # ---------------------------------------------------------

        self.last_check_time = 0.0

        # ---------------------------------------------------------
        # Statistics
        # ---------------------------------------------------------

        self.check_count = 0
        self.stats_start_time = time.time()
        self.stats_interval = 5.0

        # ---------------------------------------------------------
        # Log mode
        # ---------------------------------------------------------

        if self.liveness_model is None:
            if self.development_mode:
                self.get_logger().warning(
                    "DEVELOPMENT MODE — liveness not verified. "
                    f"dev_liveness_score={self.dev_liveness_score}"
                )
            else:
                self.get_logger().error(
                    "No liveness model loaded and "
                    "development_mode=false. "
                    "All liveness checks will return "
                    "is_live=false (FAIL CLOSED). "
                    "Set development_mode:=true to bypass "
                    "during development."
                )

        self.get_logger().info(
            f"Liveness Node started | "
            f"threshold={self.liveness_threshold} | "
            f"interval={self.liveness_interval}s | "
            f"dev_mode={self.development_mode}"
        )

    # =============================================================
    # MODEL LOADING
    # =============================================================

    def _load_model(self):
        """
        Try to load a liveness/anti-spoofing model.

        Supports Silent-Face-Anti-Spoofing ONNX models.
        """

        if not self.model_path_param:
            self.get_logger().warning(
                "No liveness model_path configured"
            )
            return

        try:
            import onnxruntime as ort

            providers = ort.get_available_providers()
            if "CUDAExecutionProvider" in providers:
                prov = ["CUDAExecutionProvider"]
            else:
                prov = ["CPUExecutionProvider"]

            self.liveness_model = ort.InferenceSession(
                self.model_path_param,
                providers=prov
            )

            self.get_logger().info(
                f"Liveness model loaded: {self.model_path_param}"
            )

        except Exception as e:
            self.get_logger().error(
                f"Failed to load liveness model: {e}"
            )
            self.liveness_model = None

    # =============================================================
    # CROP CALLBACK
    # =============================================================

    def crop_callback(self, msg):
        """Process incoming FaceCrop for liveness check."""

        # Throttle
        now = time.time()
        if now - self.last_check_time < self.liveness_interval:
            return
        self.last_check_time = now

        # ---------------------------------------------------------
        # Extract image
        # ---------------------------------------------------------

        try:
            face_img = self.bridge.imgmsg_to_cv2(
                msg.image,
                desired_encoding="bgr8"
            )
        except Exception as e:
            self.get_logger().error(
                f"CV bridge conversion failed: {e}"
            )
            return

        if face_img is None or face_img.size == 0:
            return

        # ---------------------------------------------------------
        # Run liveness check
        # ---------------------------------------------------------

        score, is_live = self._check_liveness(face_img)

        # ---------------------------------------------------------
        # Publish FaceLiveness
        # ---------------------------------------------------------

        liveness_msg = FaceLiveness()
        liveness_msg.header = msg.header
        liveness_msg.id = msg.id
        liveness_msg.score = float(score)
        liveness_msg.is_live = is_live

        self.liveness_pub.publish(liveness_msg)

        # ---------------------------------------------------------
        # Statistics
        # ---------------------------------------------------------

        self.check_count += 1
        elapsed = time.time() - self.stats_start_time

        if elapsed >= self.stats_interval:
            rate = self.check_count / elapsed

            mode_str = (
                "DEV" if self.development_mode else "PROD"
            )
            model_str = (
                "model" if self.liveness_model else "no-model"
            )

            self.get_logger().info(
                f"Liveness rate: {rate:.1f}/s | "
                f"mode={mode_str} | "
                f"{model_str} | "
                f"last_score={score:.2f} | "
                f"is_live={is_live}"
            )

            self.check_count = 0
            self.stats_start_time = time.time()

    # =============================================================
    # LIVENESS CHECK
    # =============================================================

    def _check_liveness(self, face_img):
        """
        Check if a face is live (not a spoof).

        Returns:
            tuple: (score, is_live)
        """

        # ---------------------------------------------------------
        # Real model path
        # ---------------------------------------------------------

        if self.liveness_model is not None:
            try:
                return self._run_model(face_img)
            except Exception as e:
                self.get_logger().error(
                    f"Liveness model inference failed: {e}"
                )
                # Fail closed on model error
                return 0.0, False

        # ---------------------------------------------------------
        # No model available
        # ---------------------------------------------------------

        if self.development_mode:
            # Development mode: return configurable score
            self.get_logger().warning(
                "DEVELOPMENT MODE — liveness not verified",
                throttle_duration_sec=10.0
            )

            score = self.dev_liveness_score
            is_live = score >= self.liveness_threshold
            return score, is_live
        else:
            # Production mode without model: FAIL CLOSED
            return 0.0, False

    def _run_model(self, face_img):
        """
        Run the actual liveness ONNX model.

        Args:
            face_img: BGR face crop

        Returns:
            tuple: (score, is_live)
        """
        # Get model input details
        input_details = self.liveness_model.get_inputs()
        input_name = input_details[0].name
        input_shape = input_details[0].shape

        # Resize to model input size
        h, w = input_shape[2], input_shape[3]
        resized = cv2.resize(face_img, (w, h))

        # Normalize to [0, 1]
        blob = resized.astype(np.float32) / 255.0

        # CHW format
        blob = np.transpose(blob, (2, 0, 1))

        # Add batch dimension
        blob = np.expand_dims(blob, axis=0)

        # Run inference
        outputs = self.liveness_model.run(
            None,
            {input_name: blob}
        )

        # Interpret output
        # Most anti-spoofing models output
        # [spoof_prob, live_prob] or a single score
        output = outputs[0].flatten()

        if len(output) >= 2:
            score = float(output[1])  # live probability
        else:
            score = float(output[0])

        is_live = score >= self.liveness_threshold

        return score, is_live


# =================================================================
# MAIN
# =================================================================

def main(args=None):

    rclpy.init(args=args)

    node = LivenessNode()

    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
