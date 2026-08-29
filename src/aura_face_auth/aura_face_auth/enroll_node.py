#!/usr/bin/env python3
"""
AURA Face Enrollment Node

Collects face embeddings for a user and stores them in the database.
Correlates FaceCrop ↔ FaceEmbedding by id + timestamp.

Usage:
    ros2 run aura_face_auth enroll_node \
        --ros-args -p username:=thirumalesh -p num_samples:=15
"""

import time

import numpy as np

import rclpy
from rclpy.node import Node
from cv_bridge import CvBridge

from aura_face_msgs.msg import FaceCrop
from aura_face_msgs.msg import FaceEmbedding
from aura_face_msgs.msg import FaceDetections

from aura_face_auth.database import FaceAuthDatabase
from aura_face_auth.utils import (
    normalize_embedding,
    calculate_face_quality,
    estimate_blur,
    check_brightness,
)


class EnrollNode(Node):

    def __init__(self):
        super().__init__("enroll_node")

        # ---------------------------------------------------------
        # Parameters
        # ---------------------------------------------------------

        self.declare_parameter("username", "")
        self.declare_parameter("num_samples", 15)
        self.declare_parameter("min_quality", 0.3)
        self.declare_parameter("min_confidence", 0.6)
        self.declare_parameter("min_face_size", 50)
        self.declare_parameter("db_path", "")
        self.declare_parameter("max_correlation_age", 1.0)

        self.username = self.get_parameter("username").value
        self.num_samples = self.get_parameter("num_samples").value
        self.min_quality = self.get_parameter("min_quality").value
        self.min_confidence = self.get_parameter(
            "min_confidence"
        ).value
        self.min_face_size = self.get_parameter(
            "min_face_size"
        ).value

        db_path = self.get_parameter("db_path").value
        self.max_correlation_age = self.get_parameter(
            "max_correlation_age"
        ).value

        if not self.username:
            self.get_logger().error(
                "No username specified. "
                "Use: --ros-args -p username:=<name>"
            )
            raise ValueError("username parameter is required")

        # ---------------------------------------------------------
        # Database
        # ---------------------------------------------------------

        self.db = FaceAuthDatabase(
            db_path if db_path else None
        )

        # ---------------------------------------------------------
        # Subscribers
        # ---------------------------------------------------------

        self.crop_sub = self.create_subscription(
            FaceCrop,
            "/face/crops",
            self.crop_callback,
            10
        )

        self.embedding_sub = self.create_subscription(
            FaceEmbedding,
            "/face/embedding",
            self.embedding_callback,
            10
        )

        self.detections_sub = self.create_subscription(
            FaceDetections,
            "/face/detections",
            self.detections_callback,
            10
        )

        # ---------------------------------------------------------
        # OpenCV bridge
        # ---------------------------------------------------------

        self.bridge = CvBridge()

        # ---------------------------------------------------------
        # Enrollment state
        # ---------------------------------------------------------

        # Pending crops waiting for embedding correlation
        self.pending_crops = {}  # face_id → {crop_data, timestamp}

        # Collected good embeddings
        self.collected_embeddings = []
        self.collected_qualities = []

        self.rejected_count = 0
        self.latest_num_faces = 0

        self.enrollment_complete = False

        self.get_logger().info(
            f"Enrollment started for '{self.username}' | "
            f"collecting {self.num_samples} samples"
        )
        self.get_logger().info(
            "Look at the camera. Move your head slightly "
            "between captures for better enrollment."
        )

    # =============================================================
    # CALLBACKS
    # =============================================================

    def detections_callback(self, msg):
        """Track number of faces."""
        self.latest_num_faces = len(msg.faces)

    def crop_callback(self, msg):
        """Store pending crop for correlation."""

        if self.enrollment_complete:
            return

        now = time.time()

        # ---------------------------------------------------------
        # Reject: multiple faces
        # ---------------------------------------------------------

        if self.latest_num_faces > 1:
            self.get_logger().warning(
                "Multiple faces detected — sample rejected",
                throttle_duration_sec=3.0
            )
            self.rejected_count += 1
            return

        # ---------------------------------------------------------
        # Reject: low confidence
        # ---------------------------------------------------------

        if msg.confidence < self.min_confidence:
            self.rejected_count += 1
            return

        # ---------------------------------------------------------
        # Reject: small face
        # ---------------------------------------------------------

        try:
            face_img = self.bridge.imgmsg_to_cv2(
                msg.image, desired_encoding="bgr8"
            )
        except Exception:
            self.rejected_count += 1
            return

        if face_img is None or face_img.size == 0:
            self.rejected_count += 1
            return

        h, w = face_img.shape[:2]
        if w < self.min_face_size or h < self.min_face_size:
            self.rejected_count += 1
            return

        # ---------------------------------------------------------
        # Reject: blurry
        # ---------------------------------------------------------

        blur = estimate_blur(face_img)
        if blur < 15.0:
            self.rejected_count += 1
            return

        # ---------------------------------------------------------
        # Reject: too dark or too bright
        # ---------------------------------------------------------

        brightness = check_brightness(face_img)
        if brightness < 40.0 or brightness > 220.0:
            self.rejected_count += 1
            return

        # ---------------------------------------------------------
        # Store pending crop
        # ---------------------------------------------------------

        self.pending_crops[msg.id] = {
            "confidence": msg.confidence,
            "landmarks": list(msg.landmarks),
            "timestamp": now,
            "face_img": face_img,
        }

        # Clean old pending crops
        self._clean_pending(now)

    def embedding_callback(self, msg):
        """Correlate embedding with pending crop by face ID."""

        if self.enrollment_complete:
            return

        now = time.time()

        # ---------------------------------------------------------
        # Correlate by face ID
        # ---------------------------------------------------------

        if msg.id not in self.pending_crops:
            self.get_logger().debug(
                f"Embedding face_id={msg.id} has no "
                f"matching pending crop — skipped"
            )
            return

        crop_data = self.pending_crops[msg.id]

        # Check correlation freshness
        age = abs(now - crop_data["timestamp"])
        if age > self.max_correlation_age:
            self.get_logger().debug(
                f"Correlation too old ({age:.1f}s) — skipped"
            )
            del self.pending_crops[msg.id]
            return

        # ---------------------------------------------------------
        # Quality check on embedding
        # ---------------------------------------------------------

        if msg.quality < self.min_quality:
            self.rejected_count += 1
            del self.pending_crops[msg.id]
            return

        # ---------------------------------------------------------
        # Accept sample
        # ---------------------------------------------------------

        embedding = np.array(msg.embedding, dtype=np.float32)
        embedding = normalize_embedding(embedding)

        self.collected_embeddings.append(embedding)
        self.collected_qualities.append(msg.quality)

        del self.pending_crops[msg.id]

        count = len(self.collected_embeddings)

        self.get_logger().info(
            f"Sample {count}/{self.num_samples} collected | "
            f"quality={msg.quality:.2f} | "
            f"rejected={self.rejected_count}"
        )

        # ---------------------------------------------------------
        # Check if enrollment is complete
        # ---------------------------------------------------------

        if count >= self.num_samples:
            self._complete_enrollment()

    # =============================================================
    # COMPLETE ENROLLMENT
    # =============================================================

    def _complete_enrollment(self):
        """Store collected embeddings in database."""

        self.enrollment_complete = True

        self.get_logger().info(
            f"Enrollment complete! "
            f"Collected {len(self.collected_embeddings)} samples. "
            f"Rejected {self.rejected_count} samples."
        )

        # Create or get user
        try:
            if self.db.user_exists(self.username):
                user = self.db.get_user(self.username)
                user_id = user["user_id"]
                self.get_logger().info(
                    f"Adding to existing user '{self.username}'"
                )
            else:
                user_id = self.db.create_user(self.username)
                self.get_logger().info(
                    f"Created user '{self.username}' "
                    f"(user_id={user_id})"
                )
        except Exception as e:
            self.get_logger().error(
                f"Database error: {e}"
            )
            return

        # Store each embedding individually
        for i, (emb, quality) in enumerate(
            zip(self.collected_embeddings, self.collected_qualities)
        ):
            try:
                self.db.save_embedding(user_id, emb, quality)
            except Exception as e:
                self.get_logger().error(
                    f"Failed to save embedding {i}: {e}"
                )

        total = self.db.get_embedding_count(user_id)
        self.get_logger().info(
            f"Enrollment saved. "
            f"User '{self.username}' now has "
            f"{total} templates in database."
        )

        # Shutdown after enrollment
        self.get_logger().info("Enrollment node shutting down.")
        raise SystemExit(0)

    # =============================================================
    # HELPERS
    # =============================================================

    def _clean_pending(self, now):
        """Remove stale pending crops."""
        stale = [
            fid for fid, data in self.pending_crops.items()
            if now - data["timestamp"] > self.max_correlation_age * 2
        ]
        for fid in stale:
            del self.pending_crops[fid]

    def destroy_node(self):
        if self.db:
            self.db.close()
        super().destroy_node()


# =================================================================
# MAIN
# =================================================================

def main(args=None):

    rclpy.init(args=args)

    try:
        node = EnrollNode()
        rclpy.spin(node)
    except (KeyboardInterrupt, SystemExit):
        pass
    except ValueError as e:
        print(f"Error: {e}")
    finally:
        rclpy.shutdown()


if __name__ == "__main__":
    main()
