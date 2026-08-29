#!/usr/bin/env python3
"""
AURA Face Detector Node

Subscribes to /camera/image_raw.
Publishes:
    /face/detections (FaceDetections)
    /face/crops      (FaceCrop — one per detected face)
    /face/debug      (sensor_msgs/Image)

Uses SCRFD detection model via InsightFace.
Detection only — no recognition, age, or gender.
"""

import time

import cv2
import numpy as np

import rclpy
from rclpy.node import Node

from sensor_msgs.msg import Image
from cv_bridge import CvBridge

from insightface.app import FaceAnalysis

from aura_face_msgs.msg import FaceDetection
from aura_face_msgs.msg import FaceDetections
from aura_face_msgs.msg import FaceCrop
from aura_face_msgs.msg import AuthenticationStatus


class FaceDetectorNode(Node):

    def __init__(self):
        super().__init__("face_detector_node")

        # ---------------------------------------------------------
        # ROS 2 parameters
        # ---------------------------------------------------------

        self.declare_parameter("det_thresh", 0.5)
        self.declare_parameter("det_size", 640)
        self.declare_parameter("process_every_n_frames", 2)
        self.declare_parameter("process_every_n_frames_auth", 4)
        self.declare_parameter("execution_provider", "auto")

        self.det_thresh = self.get_parameter(
            "det_thresh"
        ).value

        det_size = self.get_parameter("det_size").value
        self.det_size = (det_size, det_size)

        self.process_every_n_frames = self.get_parameter(
            "process_every_n_frames"
        ).value

        self.process_every_n_frames_auth = self.get_parameter(
            "process_every_n_frames_auth"
        ).value

        self.execution_provider = self.get_parameter(
            "execution_provider"
        ).value

        # ---------------------------------------------------------
        # ROS publishers
        # ---------------------------------------------------------

        self.detection_pub = self.create_publisher(
            FaceDetections,
            "/face/detections",
            10
        )

        self.crop_pub = self.create_publisher(
            FaceCrop,
            "/face/crops",
            10
        )

        self.debug_pub = self.create_publisher(
            Image,
            "/face/debug",
            10
        )

        # ---------------------------------------------------------
        # ROS subscriber
        # ---------------------------------------------------------

        self.image_sub = self.create_subscription(
            Image,
            "/camera/image_raw",
            self.image_callback,
            10
        )

        self.auth_sub = self.create_subscription(
            AuthenticationStatus,
            "/auth/status",
            self.auth_status_callback,
            10
        )
        self.auth_status = None

        # ---------------------------------------------------------
        # OpenCV <-> ROS bridge
        # ---------------------------------------------------------

        self.bridge = CvBridge()

        # ---------------------------------------------------------
        # Face detector
        # ---------------------------------------------------------
        #
        # We use only the detection model from InsightFace.
        #
        # allowed_modules=["detection"]
        #
        # This prevents recognition / age / gender models from
        # being loaded.
        # ---------------------------------------------------------

        self.get_logger().info("Loading SCRFD detector...")

        # Determine GPU/CPU
        ctx_id = -1  # CPU default
        if self.execution_provider == "auto":
            try:
                import onnxruntime as ort
                if "CUDAExecutionProvider" in ort.get_available_providers():
                    ctx_id = 0
                    self.get_logger().info("Using GPU")
                else:
                    self.get_logger().info("Using CPU")
            except ImportError:
                self.get_logger().info("Using CPU (onnxruntime check skipped)")
        elif self.execution_provider == "cuda":
            ctx_id = 0

        self.face_app = FaceAnalysis(
            name="buffalo_s",
            allowed_modules=["detection"]
        )

        self.face_app.prepare(
            ctx_id=ctx_id,
            det_thresh=self.det_thresh,
            det_size=self.det_size
        )

        self.get_logger().info(
            "SCRFD detector initialized"
        )

        # ---------------------------------------------------------
        # Detection parameters
        # ---------------------------------------------------------

        self.frame_counter = 0

        # ---------------------------------------------------------
        # FPS tracking
        # ---------------------------------------------------------

        self.processed_frames = 0
        self.fps_start_time = time.time()
        self.fps_log_interval = 5.0

        self.get_logger().info(
            f"Face Detector Node started | "
            f"thresh={self.det_thresh} | "
            f"size={self.det_size} | "
            f"skip={self.process_every_n_frames}"
        )

    # =============================================================
    # CALLBACKS
    # =============================================================

    def auth_status_callback(self, msg):
        self.auth_status = msg

    def image_callback(self, msg):

        self.frame_counter += 1

        # ---------------------------------------------------------
        # Skip frames to reduce CPU/GPU load
        # ---------------------------------------------------------

        # State-aware: skip more frames when authenticated to free CPU
        skip = self.process_every_n_frames
        if self.auth_status and self.auth_status.authenticated:
            skip = self.process_every_n_frames_auth

        if self.frame_counter % skip != 0:
            return

        # ---------------------------------------------------------
        # ROS Image -> OpenCV
        # ---------------------------------------------------------

        try:

            frame = self.bridge.imgmsg_to_cv2(
                msg,
                desired_encoding="bgr8"
            )

        except Exception as e:

            self.get_logger().error(
                f"CV bridge conversion failed: {e}"
            )

            return

        # ---------------------------------------------------------
        # Run SCRFD
        # ---------------------------------------------------------

        try:

            faces = self.face_app.get(frame)

        except Exception as e:

            self.get_logger().error(
                f"Face detection failed: {e}"
            )

            return

        # ---------------------------------------------------------
        # Create FaceDetections message
        # ---------------------------------------------------------

        detections_msg = FaceDetections()

        detections_msg.header = msg.header

        # ---------------------------------------------------------
        # Debug image
        # ---------------------------------------------------------

        debug_frame = frame.copy()

        # ---------------------------------------------------------
        # Process every detected face
        # ---------------------------------------------------------

        height, width = frame.shape[:2]

        for face_id, face in enumerate(faces):

            # Bounding box

            bbox = face.bbox.astype(int)

            x1 = int(bbox[0])
            y1 = int(bbox[1])
            x2 = int(bbox[2])
            y2 = int(bbox[3])

            confidence = float(face.det_score)

            # -----------------------------------------------------
            # Clamp bounding box to image dimensions
            # -----------------------------------------------------

            x1 = max(0, min(x1, width - 1))
            y1 = max(0, min(y1, height - 1))

            x2 = max(0, min(x2, width - 1))
            y2 = max(0, min(y2, height - 1))

            # Invalid bounding box

            if x2 <= x1 or y2 <= y1:
                continue

            # -----------------------------------------------------
            # Create custom FaceDetection message
            # -----------------------------------------------------

            detection = FaceDetection()

            detection.id = face_id

            detection.x = float(x1)
            detection.y = float(y1)

            detection.width = float(x2 - x1)
            detection.height = float(y2 - y1)

            detection.confidence = confidence

            # -----------------------------------------------------
            # Facial landmarks
            # -----------------------------------------------------
            #
            # SCRFD gives 5 landmarks:
            #
            # 0 = left eye
            # 1 = right eye
            # 2 = nose
            # 3 = left mouth
            # 4 = right mouth
            #
            # Store:
            #
            # x1,y1,x2,y2,...,x5,y5
            # -----------------------------------------------------

            landmarks_list = []
            if face.kps is not None:

                landmarks = face.kps.copy()
                landmarks[:, 0] -= x1
                landmarks[:, 1] -= y1

                landmarks = landmarks.flatten().astype(float)
                landmarks_list = landmarks.tolist()
                detection.landmarks = landmarks_list

            else:

                detection.landmarks = []

            detections_msg.faces.append(detection)

            # -----------------------------------------------------
            # Draw debug rectangle
            # -----------------------------------------------------

            cv2.rectangle(
                debug_frame,
                (x1, y1),
                (x2, y2),
                (0, 255, 0),
                2
            )

            # -----------------------------------------------------
            # Draw ID + confidence
            # -----------------------------------------------------

            if self.auth_status and self.auth_status.authenticated and self.auth_status.face_id == face_id:
                label = f"{self.auth_status.username} ({confidence:.2f})"
            else:
                label = f"ID: {face_id} {confidence:.2f}"

            cv2.putText(
                debug_frame,
                label,
                (x1, max(20, y1 - 10)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                (0, 255, 0),
                2
            )

            # -----------------------------------------------------
            # Draw landmarks
            # -----------------------------------------------------

            if face.kps is not None:

                for point in face.kps:

                    px = int(point[0])
                    py = int(point[1])

                    cv2.circle(
                        debug_frame,
                        (px, py),
                        3,
                        (0, 0, 255),
                        -1
                    )

            # -----------------------------------------------------
            # Crop face and publish FaceCrop for EVERY face
            # -----------------------------------------------------

            face_crop = frame[
                y1:y2,
                x1:x2
            ]

            if face_crop.size == 0:
                continue

            crop_msg = FaceCrop()
            crop_msg.header = msg.header
            crop_msg.id = face_id
            crop_msg.confidence = confidence
            crop_msg.landmarks = landmarks_list

            crop_msg.image = self.bridge.cv2_to_imgmsg(
                face_crop,
                encoding="bgr8"
            )

            self.crop_pub.publish(crop_msg)

        # ---------------------------------------------------------
        # Publish detections
        # ---------------------------------------------------------

        self.detection_pub.publish(
            detections_msg
        )

        # ---------------------------------------------------------
        # Publish debug image
        # ---------------------------------------------------------

        debug_msg = self.bridge.cv2_to_imgmsg(
            debug_frame,
            encoding="bgr8"
        )

        debug_msg.header = msg.header

        self.debug_pub.publish(
            debug_msg
        )

        # ---------------------------------------------------------
        # FPS tracking
        # ---------------------------------------------------------

        self.processed_frames += 1
        elapsed = time.time() - self.fps_start_time

        if elapsed >= self.fps_log_interval:
            fps = self.processed_frames / elapsed

            self.get_logger().info(
                f"Detector FPS: {fps:.1f} | "
                f"Faces: {len(faces)}"
            )

            self.processed_frames = 0
            self.fps_start_time = time.time()


# =================================================================
# MAIN
# =================================================================

def main(args=None):

    rclpy.init(args=args)

    node = FaceDetectorNode()

    try:

        rclpy.spin(node)

    except KeyboardInterrupt:

        pass

    finally:

        node.destroy_node()

        rclpy.shutdown()


if __name__ == "__main__":

    main()