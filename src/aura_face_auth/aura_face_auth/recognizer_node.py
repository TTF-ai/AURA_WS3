#!/usr/bin/env python3
"""
AURA Face Recognizer Node

Subscribes to /face/crops (FaceCrop) and generates ArcFace embeddings.
Publishes to /face/embedding (FaceEmbedding).

Does NOT make authentication decisions.
"""

import time

import cv2
import numpy as np

import rclpy
from rclpy.node import Node
from cv_bridge import CvBridge

from aura_face_msgs.msg import FaceCrop
from aura_face_msgs.msg import FaceEmbedding

from aura_face_auth.utils import (
    align_face,
    normalize_embedding,
    calculate_face_quality,
)


class RecognizerNode(Node):

    def __init__(self):
        super().__init__("recognizer_node")

        # ---------------------------------------------------------
        # ROS 2 parameters
        # ---------------------------------------------------------

        self.declare_parameter("recognition_interval", 0.5)
        self.declare_parameter("execution_provider", "auto")
        self.declare_parameter("model_path", "")

        self.recognition_interval = self.get_parameter(
            "recognition_interval"
        ).value

        self.execution_provider = self.get_parameter(
            "execution_provider"
        ).value

        self.model_path = self.get_parameter(
            "model_path"
        ).value

        # ---------------------------------------------------------
        # Publisher
        # ---------------------------------------------------------

        self.embedding_pub = self.create_publisher(
            FaceEmbedding,
            "/face/embedding",
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
        # Load ArcFace model
        # ---------------------------------------------------------

        self.rec_model = None
        self._load_model()

        # ---------------------------------------------------------
        # Throttling
        # ---------------------------------------------------------

        self.last_recognition_time = 0.0

        # ---------------------------------------------------------
        # Statistics
        # ---------------------------------------------------------

        self.processed_count = 0
        self.stats_start_time = time.time()
        self.stats_interval = 5.0

        self.get_logger().info(
            f"Recognizer Node started | "
            f"interval={self.recognition_interval}s | "
            f"provider={self.execution_provider}"
        )

    # =============================================================
    # MODEL LOADING
    # =============================================================

    def _load_model(self):
        """Load ArcFace recognition model."""

        try:
            import onnxruntime as ort

            # Determine execution provider
            available = ort.get_available_providers()
            self.get_logger().info(
                f"ONNX Runtime providers: {available}"
            )

            if self.execution_provider == "auto":
                if "CUDAExecutionProvider" in available:
                    providers = ["CUDAExecutionProvider"]
                    self.get_logger().info(
                        "Using GPU (CUDAExecutionProvider)"
                    )
                else:
                    providers = ["CPUExecutionProvider"]
                    self.get_logger().info(
                        "Using CPU (CPUExecutionProvider)"
                    )
            elif self.execution_provider == "cuda":
                providers = ["CUDAExecutionProvider"]
            else:
                providers = ["CPUExecutionProvider"]

            self._ort_providers = providers

        except ImportError:
            self.get_logger().error(
                "onnxruntime not installed. "
                "Install with: pip install onnxruntime"
            )
            return

        try:
            from insightface.model_zoo import get_model

            if self.model_path and self.model_path.strip():
                # Use configured model path
                model_file = self.model_path
                self.get_logger().info(
                    f"Loading ArcFace model from: {model_file}"
                )
            else:
                # Try to find model in InsightFace default cache
                import os
                cache_dir = os.path.expanduser(
                    "~/.insightface/models/buffalo_l"
                )
                model_file = os.path.join(
                    cache_dir, "w600k_r50.onnx"
                )

                if not os.path.exists(model_file):
                    # Try buffalo_s
                    cache_dir = os.path.expanduser(
                        "~/.insightface/models/buffalo_s"
                    )
                    model_file = os.path.join(
                        cache_dir, "w600k_r50.onnx"
                    )

                if not os.path.exists(model_file):
                    self.get_logger().error(
                        f"ArcFace model not found. "
                        f"Set 'model_path' parameter or download "
                        f"InsightFace models. "
                        f"Searched: {model_file}"
                    )
                    return

                self.get_logger().info(
                    f"Loading ArcFace model from: {model_file}"
                )

            self.rec_model = get_model(
                model_file,
                providers=self._ort_providers
            )
            self.rec_model.prepare(ctx_id=0)

            self.get_logger().info(
                "ArcFace recognition model loaded"
            )

        except Exception as e:
            self.get_logger().error(
                f"Failed to load ArcFace model: {e}"
            )
            self.rec_model = None

    # =============================================================
    # CROP CALLBACK
    # =============================================================

    def crop_callback(self, msg):
        """Process incoming FaceCrop message."""

        # Throttle recognition
        now = time.time()
        if now - self.last_recognition_time < self.recognition_interval:
            return
        self.last_recognition_time = now

        if self.rec_model is None:
            self.get_logger().warning(
                "Recognition model not loaded, skipping",
                throttle_duration_sec=10.0
            )
            return

        # ---------------------------------------------------------
        # Extract image from FaceCrop
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
        # Extract landmarks from FaceCrop
        # ---------------------------------------------------------

        landmarks = None
        if len(msg.landmarks) == 10:
            landmarks = np.array(
                msg.landmarks, dtype=np.float32
            ).reshape(5, 2)

        # ---------------------------------------------------------
        # Align face using landmarks
        # ---------------------------------------------------------

        if landmarks is not None:
            aligned = align_face(face_img, landmarks)
        else:
            # Fallback: resize without alignment
            aligned = cv2.resize(face_img, (112, 112))
            self.get_logger().warning(
                "No landmarks available, using unaligned face",
                throttle_duration_sec=10.0
            )

        if aligned is None:
            aligned = cv2.resize(face_img, (112, 112))

        # ---------------------------------------------------------
        # Generate embedding
        # ---------------------------------------------------------

        try:
            embedding = self.rec_model.get_feat(aligned)
            embedding = embedding.flatten()
        except Exception as e:
            self.get_logger().error(
                f"Embedding generation failed: {e}"
            )
            return

        # Normalize embedding
        embedding = normalize_embedding(embedding)

        # ---------------------------------------------------------
        # Calculate quality
        # ---------------------------------------------------------

        quality = calculate_face_quality(
            face_img,
            confidence=msg.confidence,
            landmarks=msg.landmarks if len(msg.landmarks) > 0 else None
        )

        # ---------------------------------------------------------
        # Publish FaceEmbedding
        # ---------------------------------------------------------

        emb_msg = FaceEmbedding()
        emb_msg.header = msg.header
        emb_msg.id = msg.id
        emb_msg.embedding = embedding.tolist()
        emb_msg.quality = float(quality)

        self.embedding_pub.publish(emb_msg)

        # ---------------------------------------------------------
        # Statistics
        # ---------------------------------------------------------

        self.processed_count += 1
        elapsed = time.time() - self.stats_start_time

        if elapsed >= self.stats_interval:
            rate = self.processed_count / elapsed

            self.get_logger().info(
                f"Recognition rate: {rate:.1f}/s | "
                f"embedding dim: {len(embedding)} | "
                f"quality: {quality:.2f}"
            )

            self.processed_count = 0
            self.stats_start_time = time.time()


# =================================================================
# MAIN
# =================================================================

def main(args=None):

    rclpy.init(args=args)

    node = RecognizerNode()

    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
