#!/usr/bin/env python3
"""
AURA Authentication Node

Correlates face embeddings + liveness results by face ID + timestamp.
Makes authentication decisions.
Publishes /auth/status (AuthenticationStatus).

Does NOT control robot motors/navigation directly.
"""

import time
from enum import Enum

import numpy as np

import rclpy
from rclpy.node import Node

from aura_face_msgs.msg import FaceDetections
from aura_face_msgs.msg import FaceEmbedding
from aura_face_msgs.msg import FaceLiveness
from aura_face_msgs.msg import AuthenticationStatus

from aura_face_auth.database import FaceAuthDatabase
from aura_face_auth.utils import cosine_similarity


# =================================================================
# AUTH STATES
# =================================================================

class AuthState(Enum):
    UNAUTHENTICATED = "UNAUTHENTICATED"
    AUTHENTICATING = "AUTHENTICATING"
    AUTHENTICATED = "AUTHENTICATED"
    EXPIRED = "EXPIRED"
    LOCKED = "LOCKED"


class AuthNode(Node):

    def __init__(self):
        super().__init__("auth_node")

        # ---------------------------------------------------------
        # ROS 2 parameters
        # ---------------------------------------------------------

        self.declare_parameter("similarity_threshold", 0.4)
        self.declare_parameter("authentication_timeout", 60.0)
        self.declare_parameter("reverify_interval", 10.0)
        self.declare_parameter("allow_multiple_faces", False)
        self.declare_parameter("min_quality", 0.3)
        self.declare_parameter("liveness_threshold", 0.5)
        self.declare_parameter("db_path", "")
        self.declare_parameter("max_signal_age", 2.0)
        self.declare_parameter("face_timeout", 5.0)
        self.declare_parameter("lock_cooldown", 3.0)

        self.similarity_threshold = self.get_parameter(
            "similarity_threshold"
        ).value

        self.authentication_timeout = self.get_parameter(
            "authentication_timeout"
        ).value

        self.reverify_interval = self.get_parameter(
            "reverify_interval"
        ).value

        self.allow_multiple_faces = self.get_parameter(
            "allow_multiple_faces"
        ).value

        self.min_quality = self.get_parameter(
            "min_quality"
        ).value

        self.liveness_threshold = self.get_parameter(
            "liveness_threshold"
        ).value

        db_path = self.get_parameter("db_path").value
        self.max_signal_age = self.get_parameter(
            "max_signal_age"
        ).value

        self.face_timeout = self.get_parameter(
            "face_timeout"
        ).value

        self.lock_cooldown = self.get_parameter(
            "lock_cooldown"
        ).value

        # ---------------------------------------------------------
        # Publisher
        # ---------------------------------------------------------

        self.status_pub = self.create_publisher(
            AuthenticationStatus,
            "/auth/status",
            10
        )

        # ---------------------------------------------------------
        # Subscribers
        # ---------------------------------------------------------

        self.embedding_sub = self.create_subscription(
            FaceEmbedding,
            "/face/embedding",
            self.embedding_callback,
            10
        )

        self.liveness_sub = self.create_subscription(
            FaceLiveness,
            "/face/liveness",
            self.liveness_callback,
            10
        )

        self.detections_sub = self.create_subscription(
            FaceDetections,
            "/face/detections",
            self.detections_callback,
            10
        )

        # ---------------------------------------------------------
        # Database
        # ---------------------------------------------------------

        self.db = FaceAuthDatabase(
            db_path if db_path else None
        )

        # Load enrolled embeddings into memory
        self.enrolled = {}
        self._reload_enrolled()

        # ---------------------------------------------------------
        # State
        # ---------------------------------------------------------

        self.state = AuthState.UNAUTHENTICATED
        self.authenticated_username = ""
        self.authenticated_user_id = None
        self.authenticated_face_id = -1
        self.best_similarity = 0.0
        self.auth_time = 0.0
        self.last_reverify_time = 0.0
        self.lock_time = 0.0

        # Latest signals (keyed by face ID)
        self.latest_embeddings = {}
        self.latest_liveness = {}
        self.latest_num_faces = 0
        self.last_face_seen_time = 0.0

        # ---------------------------------------------------------
        # Auth evaluation timer
        # ---------------------------------------------------------

        self.auth_timer = self.create_timer(
            0.5,
            self.evaluate_auth
        )

        # Periodically reload enrolled embeddings
        self.reload_timer = self.create_timer(
            30.0,
            self._reload_enrolled
        )

        self.get_logger().info(
            f"Auth Node started | "
            f"sim_thresh={self.similarity_threshold} "
            f"(DEV starting value) | "
            f"timeout={self.authentication_timeout}s | "
            f"reverify={self.reverify_interval}s | "
            f"multi_face={self.allow_multiple_faces}"
        )

    # =============================================================
    # RELOAD ENROLLED EMBEDDINGS
    # =============================================================

    def _reload_enrolled(self):
        """Reload enrolled embeddings from database."""
        try:
            self.enrolled = self.db.get_all_embeddings()

            total = sum(
                len(embs) for embs in self.enrolled.values()
            )

            self.get_logger().info(
                f"Enrolled users: {len(self.enrolled)} | "
                f"total templates: {total}"
            )
        except Exception as e:
            self.get_logger().error(
                f"Failed to reload enrollments: {e}"
            )

    # =============================================================
    # CALLBACKS
    # =============================================================

    def embedding_callback(self, msg):
        """Store latest embedding keyed by face ID."""
        now = time.time()

        self.latest_embeddings[msg.id] = {
            "embedding": np.array(
                msg.embedding, dtype=np.float32
            ),
            "quality": msg.quality,
            "timestamp": now,
            "header": msg.header,
        }

        self.last_face_seen_time = now

    def liveness_callback(self, msg):
        """Store latest liveness keyed by face ID."""
        now = time.time()

        self.latest_liveness[msg.id] = {
            "score": msg.score,
            "is_live": msg.is_live,
            "timestamp": now,
        }

    def detections_callback(self, msg):
        """Track number of faces detected."""
        self.latest_num_faces = len(msg.faces)

        if self.latest_num_faces > 0:
            self.last_face_seen_time = time.time()

    # =============================================================
    # AUTH EVALUATION
    # =============================================================

    def evaluate_auth(self):
        """Periodic authentication state evaluation."""

        now = time.time()

        # ---------------------------------------------------------
        # State: LOCKED → cooldown → UNAUTHENTICATED
        # ---------------------------------------------------------

        if self.state == AuthState.LOCKED:
            if now - self.lock_time >= self.lock_cooldown:
                self.state = AuthState.UNAUTHENTICATED
                self.get_logger().info(
                    "Lock cooldown expired → UNAUTHENTICATED"
                )
            self._publish_status(now)
            return

        # ---------------------------------------------------------
        # State: EXPIRED → UNAUTHENTICATED
        # ---------------------------------------------------------

        if self.state == AuthState.EXPIRED:
            self.state = AuthState.UNAUTHENTICATED
            self._publish_status(now)
            return

        # ---------------------------------------------------------
        # State: AUTHENTICATED → check timeout / reverify
        # ---------------------------------------------------------

        if self.state == AuthState.AUTHENTICATED:

            # Check authentication timeout
            if now - self.auth_time >= self.authentication_timeout:
                self.get_logger().info(
                    "Authentication timeout → EXPIRED"
                )
                self.state = AuthState.EXPIRED
                self._clear_auth()
                self._publish_status(now)
                return

            # Check face lost
            if now - self.last_face_seen_time >= self.face_timeout:
                self.get_logger().warning(
                    "Face lost → LOCKED"
                )
                self.state = AuthState.LOCKED
                self.lock_time = now
                self._clear_auth()
                self._publish_status(now)
                return

            # Multi-face check
            if (not self.allow_multiple_faces
                    and self.latest_num_faces > 1):
                self.get_logger().warning(
                    "Multiple faces detected → LOCKED"
                )
                self.state = AuthState.LOCKED
                self.lock_time = now
                self._clear_auth()
                self._publish_status(now)
                return

            # Periodic re-verification
            if now - self.last_reverify_time >= self.reverify_interval:
                self._reverify(now)

            self._publish_status(now)
            return

        # ---------------------------------------------------------
        # State: UNAUTHENTICATED / AUTHENTICATING → attempt auth
        # ---------------------------------------------------------

        if self.latest_num_faces == 0:
            self._publish_status(now)
            return

        # Multi-face safety
        if (not self.allow_multiple_faces
                and self.latest_num_faces > 1):
            self.get_logger().warning(
                "Multiple faces — not authenticating",
                throttle_duration_sec=5.0
            )
            self._publish_status(now)
            return

        self.state = AuthState.AUTHENTICATING
        self._attempt_auth(now)
        self._publish_status(now)

    # =============================================================
    # ATTEMPT AUTHENTICATION
    # =============================================================

    def _attempt_auth(self, now):
        """Try to authenticate using correlated signals."""

        if not self.enrolled:
            return

        # Find a face ID with both embedding and liveness
        matched_face_id = None
        matched_emb = None
        matched_liveness = None

        for face_id, emb_data in self.latest_embeddings.items():

            # Check signal freshness
            if now - emb_data["timestamp"] > self.max_signal_age:
                continue

            # Check quality
            if emb_data["quality"] < self.min_quality:
                continue

            # Check for matching liveness
            if face_id not in self.latest_liveness:
                continue

            liv_data = self.latest_liveness[face_id]

            if now - liv_data["timestamp"] > self.max_signal_age:
                continue

            matched_face_id = face_id
            matched_emb = emb_data
            matched_liveness = liv_data
            break

        if matched_emb is None or matched_liveness is None:
            self.state = AuthState.UNAUTHENTICATED
            return

        # ---------------------------------------------------------
        # Liveness check
        # ---------------------------------------------------------

        if not matched_liveness["is_live"]:
            self.state = AuthState.UNAUTHENTICATED
            return

        if matched_liveness["score"] < self.liveness_threshold:
            self.state = AuthState.UNAUTHENTICATED
            return

        # ---------------------------------------------------------
        # Identity matching against all enrolled users
        # ---------------------------------------------------------

        best_username = ""
        best_similarity = -1.0
        best_user_id = None

        embedding = matched_emb["embedding"]

        for username, templates in self.enrolled.items():
            for template in templates:
                sim = cosine_similarity(embedding, template)
                if sim > best_similarity:
                    best_similarity = sim
                    best_username = username
                    # Get user_id
                    user = self.db.get_user(username)
                    if user:
                        best_user_id = user["user_id"]

        # ---------------------------------------------------------
        # Threshold check
        # ---------------------------------------------------------

        if best_similarity >= self.similarity_threshold:
            self.state = AuthState.AUTHENTICATED
            self.authenticated_username = best_username
            self.authenticated_user_id = best_user_id
            self.authenticated_face_id = matched_face_id
            self.best_similarity = best_similarity
            self.auth_time = now
            self.last_reverify_time = now

            self.get_logger().info(
                f"AUTHENTICATED: {best_username} | "
                f"similarity={best_similarity:.3f} | "
                f"liveness={matched_liveness['score']:.2f}"
            )
        else:
            if best_similarity != -1.0:
                self.get_logger().warning(
                    f"Auth failed: best similarity {best_similarity:.3f} < threshold {self.similarity_threshold}",
                    throttle_duration_sec=2.0
                )
            self.state = AuthState.UNAUTHENTICATED

    # =============================================================
    # RE-VERIFICATION
    # =============================================================

    def _reverify(self, now):
        """
        Re-verify by matching the live embedding against ALL
        enrolled users.  This allows the system to dynamically
        switch identity when a different enrolled person steps
        in front of the camera.
        """

        self.last_reverify_time = now

        if not self.enrolled:
            self.state = AuthState.LOCKED
            self.lock_time = now
            self._clear_auth()
            return

        # Find a fresh embedding
        fresh_emb = None
        fresh_face_id = None

        for face_id, emb_data in self.latest_embeddings.items():
            if now - emb_data["timestamp"] <= self.max_signal_age:
                fresh_emb = emb_data["embedding"]
                fresh_face_id = face_id
                break

        if fresh_emb is None:
            # No fresh embedding — face may be temporarily obscured
            # Don't lock immediately, face_timeout handles that
            return

        # Check liveness for same face
        if fresh_face_id in self.latest_liveness:
            liv = self.latest_liveness[fresh_face_id]
            if now - liv["timestamp"] <= self.max_signal_age:
                if not liv["is_live"]:
                    self.get_logger().warning(
                        "Reverify: liveness failed → LOCKED"
                    )
                    self.state = AuthState.LOCKED
                    self.lock_time = now
                    self._clear_auth()
                    return

        # Compare against ALL enrolled users
        best_sim = -1.0
        best_username = ""
        best_user_id = None

        for username, templates in self.enrolled.items():
            for template in templates:
                sim = cosine_similarity(fresh_emb, template)
                if sim > best_sim:
                    best_sim = sim
                    best_username = username
                    user = self.db.get_user(username)
                    if user:
                        best_user_id = user["user_id"]

        if best_sim < self.similarity_threshold:
            self.get_logger().warning(
                f"Reverify: similarity={best_sim:.3f} "
                f"< threshold={self.similarity_threshold} → LOCKED"
            )
            self.state = AuthState.LOCKED
            self.lock_time = now
            self._clear_auth()
        else:
            # Switch identity if a different user matches better
            if best_username != self.authenticated_username:
                self.get_logger().info(
                    f"Identity switch: "
                    f"{self.authenticated_username} → "
                    f"{best_username} | "
                    f"similarity={best_sim:.3f}"
                )
            self.authenticated_username = best_username
            self.authenticated_user_id = best_user_id
            self.authenticated_face_id = fresh_face_id
            self.best_similarity = best_sim

    # =============================================================
    # HELPERS
    # =============================================================

    def _clear_auth(self):
        """Clear authentication state."""
        self.authenticated_username = ""
        self.authenticated_user_id = None
        self.authenticated_face_id = -1
        self.best_similarity = 0.0

    def _publish_status(self, now):
        """Publish AuthenticationStatus message."""

        msg = AuthenticationStatus()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.header.frame_id = "auth"

        if self.state == AuthState.AUTHENTICATED:
            msg.authenticated = True
            msg.username = self.authenticated_username
            msg.liveness_passed = True
            msg.face_id = self.authenticated_face_id
        else:
            # No info leak on failure
            msg.authenticated = False
            msg.username = ""
            msg.liveness_passed = False
            msg.face_id = -1

        msg.confidence = float(self.best_similarity)
        msg.similarity = float(self.best_similarity)

        self.status_pub.publish(msg)

    # =============================================================
    # CLEANUP
    # =============================================================

    def destroy_node(self):
        if self.db:
            self.db.close()
        super().destroy_node()


# =================================================================
# MAIN
# =================================================================

def main(args=None):

    rclpy.init(args=args)

    node = AuthNode()

    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
