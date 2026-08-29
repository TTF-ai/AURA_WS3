#!/usr/bin/env python3
"""
AURA Human Follow Node

Follows an authenticated user using:
  - YOLO11n person detection
  - ByteTrack multi-object tracking
  - Face ↔ person association
  - LiDAR distance estimation
  - Proportional follow controller

Version 1 limitation:
  Relies on ByteTrack maintaining the target track.
  If the target is fully occluded or ByteTrack loses the track
  and creates a new ID, the robot stops rather than blindly
  following another person.

Subscribes:
  /camera/image_raw   (sensor_msgs/Image)
  /scan               (sensor_msgs/LaserScan)
  /auth/status        (aura_face_msgs/AuthenticationStatus)
  /face/detections    (aura_face_msgs/FaceDetections)

Publishes:
  /cmd_vel            (geometry_msgs/Twist)
  /follow/debug       (sensor_msgs/Image)
"""

import math
import time
import threading
from enum import Enum

import cv2
import numpy as np

# Patch for older SciPy versions used by ByteTrack
if not hasattr(np, "long"):
    np.long = int

import rclpy
from rclpy.node import Node

import torch
torch.set_num_threads(4)  # Prevent CPU thread contention lag

from sensor_msgs.msg import Image, LaserScan
from geometry_msgs.msg import Twist
from cv_bridge import CvBridge
from rclpy.qos import qos_profile_sensor_data

from aura_face_msgs.msg import AuthenticationStatus
from aura_face_msgs.msg import FaceDetections
from aura_follow_msgs.msg import TargetPerson


# =================================================================
# FOLLOW STATES
# =================================================================

class FollowState(Enum):
    IDLE = "IDLE"
    WAITING_FOR_AUTH = "WAITING_FOR_AUTH"
    TARGET_ACQUISITION = "TARGET_ACQUISITION"
    FOLLOWING = "FOLLOWING"
    TARGET_LOST = "TARGET_LOST"
    REACQUIRE = "REACQUIRE"
    STOPPED = "STOPPED"


# =================================================================
# HUMAN FOLLOW NODE
# =================================================================

class HumanFollowNode(Node):

    def __init__(self):
        super().__init__("human_follow_node")

        # ---------------------------------------------------------
        # ROS 2 parameters
        # ---------------------------------------------------------

        self.declare_parameter("person_confidence_threshold", 0.5)
        self.declare_parameter("camera_horizontal_fov_deg", 70.0)
        self.declare_parameter("lidar_angle_window_deg", 15.0)
        self.declare_parameter("desired_distance", 1.5)
        self.declare_parameter("min_follow_distance", 0.8)
        self.declare_parameter("max_follow_distance", 3.0)
        self.declare_parameter("emergency_distance", 0.5)
        self.declare_parameter("horizontal_deadzone", 50)
        self.declare_parameter("Kp_linear", 0.25)
        self.declare_parameter("Kp_angular", 0.003)
        self.declare_parameter("max_linear_speed", 0.35)
        self.declare_parameter("max_angular_speed", 0.6)
        self.declare_parameter("target_lost_timeout", 1.0)
        self.declare_parameter("reacquire_timeout", 5.0)
        self.declare_parameter("device", "auto")
        self.declare_parameter("yolo_model", "yolo11n.pt")
        self.declare_parameter("process_every_n_frames", 1)
        self.declare_parameter("rotation_slowdown_threshold", 150)

        self.person_conf_thresh = self.get_parameter(
            "person_confidence_threshold"
        ).value
        self.camera_hfov_deg = self.get_parameter(
            "camera_horizontal_fov_deg"
        ).value
        self.lidar_angle_window_deg = self.get_parameter(
            "lidar_angle_window_deg"
        ).value
        self.desired_distance = self.get_parameter(
            "desired_distance"
        ).value
        self.min_follow_distance = self.get_parameter(
            "min_follow_distance"
        ).value
        self.max_follow_distance = self.get_parameter(
            "max_follow_distance"
        ).value
        self.emergency_distance = self.get_parameter(
            "emergency_distance"
        ).value
        self.horizontal_deadzone = self.get_parameter(
            "horizontal_deadzone"
        ).value
        self.Kp_linear = self.get_parameter("Kp_linear").value
        self.Kp_angular = self.get_parameter("Kp_angular").value
        self.max_linear_speed = self.get_parameter(
            "max_linear_speed"
        ).value
        self.max_angular_speed = self.get_parameter(
            "max_angular_speed"
        ).value
        self.target_lost_timeout = self.get_parameter(
            "target_lost_timeout"
        ).value
        self.reacquire_timeout = self.get_parameter(
            "reacquire_timeout"
        ).value
        self.device_param = self.get_parameter("device").value
        self.yolo_model_name = self.get_parameter("yolo_model").value
        self.process_every_n = self.get_parameter(
            "process_every_n_frames"
        ).value
        self.rotation_slowdown_threshold = self.get_parameter(
            "rotation_slowdown_threshold"
        ).value

        # ---------------------------------------------------------
        # Visualization
        # ---------------------------------------------------------

        self.cmd_vel_pub = self.create_publisher(
            Twist, "/cmd_vel", 10
        )

        self.debug_pub = self.create_publisher(
            Image, "/follow/debug", 10
        )

        self.target_pub = self.create_publisher(
            TargetPerson, "/follow/target", 10
        )

        # ---------------------------------------------------------
        # Subscribers
        # ---------------------------------------------------------

        self.image_sub = self.create_subscription(
            Image,
            "/camera/image_raw",
            self.image_callback,
            qos_profile_sensor_data
        )

        self.scan_sub = self.create_subscription(
            LaserScan,
            "/scan",
            self.scan_callback,
            10
        )

        self.auth_sub = self.create_subscription(
            AuthenticationStatus,
            "/auth/status",
            self.auth_callback,
            10
        )

        self.face_det_sub = self.create_subscription(
            FaceDetections,
            "/face/detections",
            self.face_detections_callback,
            10
        )

        # ---------------------------------------------------------
        # OpenCV bridge
        # ---------------------------------------------------------

        self.bridge = CvBridge()

        # ---------------------------------------------------------
        # YOLO model
        # ---------------------------------------------------------

        self.get_logger().info("Loading YOLO model...")

        device = self._resolve_device()
        self.get_logger().info(f"YOLO device: {device}")

        from ultralytics import YOLO
        self.yolo = YOLO(self.yolo_model_name)

        self.get_logger().info(
            f"YOLO model loaded: {self.yolo_model_name}"
        )

        self.yolo_device = device

        # ---------------------------------------------------------
        # State
        # ---------------------------------------------------------

        self.state = FollowState.IDLE
        self.target_track_id = None
        self.authenticated_username = ""
        self.auth_face_id = -1

        # Latest data
        self.latest_auth = None
        self.latest_face_detections = None
        self.latest_scan = None
        self.latest_tracks = []       # list of tracked persons
        self.image_width = 640
        self.image_height = 480

        # Timing
        self.target_last_seen_time = 0.0
        self.target_lost_time = 0.0
        self.frame_counter = 0

        # FPS tracking
        self.fps_count = 0
        self.fps_start = time.time()

        # ---------------------------------------------------------
        # Control timer (runs at 10 Hz independent of camera)
        # ---------------------------------------------------------

        self.control_timer = self.create_timer(
            0.1, self.control_loop
        )

        # ---------------------------------------------------------
        # Threading for async YOLO inference
        # ---------------------------------------------------------
        self.latest_frame = None
        self.latest_header = None
        self.last_processed_stamp = None
        self.inference_thread = threading.Thread(target=self.inference_loop, daemon=True)
        self.inference_thread.start()

        # Move to WAITING_FOR_AUTH on startup
        self.state = FollowState.WAITING_FOR_AUTH

        self.get_logger().info(
            "Human Follow Node started | "
            f"state={self.state.value} | "
            f"model={self.yolo_model_name} | "
            f"device={device}"
        )

    # =============================================================
    # DEVICE RESOLUTION
    # =============================================================

    def _resolve_device(self):
        """Determine inference device."""
        if self.device_param == "cuda":
            return "cuda"
        elif self.device_param == "cpu":
            return "cpu"
        else:
            # auto
            try:
                import torch
                if torch.cuda.is_available():
                    return "cuda"
            except ImportError:
                pass
            return "cpu"

    # =============================================================
    # CALLBACKS
    # =============================================================

    def auth_callback(self, msg):
        """Handle authentication status updates."""
        prev_auth = (
            self.latest_auth.authenticated
            if self.latest_auth else False
        )
        self.latest_auth = msg

        # Authentication revoked → immediate stop
        if prev_auth and not msg.authenticated:
            self.get_logger().warning(
                "Authentication revoked → STOPPED"
            )
            self._stop_following()
            self.state = FollowState.STOPPED
            self._publish_zero_vel()

        # New authentication
        if msg.authenticated and not prev_auth:
            self.get_logger().info(
                f"User authenticated: {msg.username} "
                f"(face_id={msg.face_id}) → "
                f"TARGET_ACQUISITION"
            )
            self.authenticated_username = msg.username
            self.auth_face_id = msg.face_id
            self.state = FollowState.TARGET_ACQUISITION

    def face_detections_callback(self, msg):
        """Store latest face detections for association."""
        self.latest_face_detections = msg

    def scan_callback(self, msg):
        """Store latest LiDAR scan."""
        self.latest_scan = msg

    def image_callback(self, msg):
        """Buffer frames and publish debug stream at camera FPS."""
        try:
            frame = self.bridge.imgmsg_to_cv2(
                msg, desired_encoding="bgr8"
            )
        except Exception as e:
            self.get_logger().error(
                f"CV bridge failed: {e}"
            )
            return

        self.image_height, self.image_width = frame.shape[:2]
        
        # Store for async inference
        self.latest_frame = frame
        self.latest_header = msg.header

    def inference_loop(self):
        """Asynchronous YOLO inference loop."""
        while rclpy.ok():
            if self.latest_frame is None or self.latest_header is None:
                time.sleep(0.005)
                continue
                
            # Frame dropping: only process if it's a new frame we haven't seen yet
            if self.last_processed_stamp == self.latest_header.stamp:
                time.sleep(0.01)
                continue
            self.last_processed_stamp = self.latest_header.stamp

            frame = self.latest_frame.copy()
            header = self.latest_header
            self.frame_counter += 1

            # Skip frames if configured for inference
            if self.frame_counter % self.process_every_n != 0:
                continue

            # ---------------------------------------------------------
            # YOLO + ByteTrack
            # ---------------------------------------------------------
            try:
                results = self.yolo.track(
                    frame,
                    persist=True,
                    tracker="bytetrack.yaml",
                    classes=[0],  # person class only
                    conf=self.person_conf_thresh,
                    device=self.yolo_device,
                    imgsz=320,    # Reduce resolution for faster CPU inference
                    verbose=False,
                )
            except Exception as e:
                self.get_logger().error(
                    f"YOLO tracking failed: {e}"
                )
                time.sleep(0.005)
                continue

            # ---------------------------------------------------------
            # Extract tracked persons
            # ---------------------------------------------------------
            tracks = []
            if (results and len(results) > 0
                    and results[0].boxes is not None):
                boxes = results[0].boxes
                for i in range(len(boxes)):
                    box = boxes[i]
                    if box.id is None:
                        continue
                    track_id = int(box.id.item())
                    xyxy = box.xyxy[0].cpu().numpy()
                    conf = float(box.conf.item())

                    tracks.append({
                        "track_id": track_id,
                        "x1": int(xyxy[0]),
                        "y1": int(xyxy[1]),
                        "x2": int(xyxy[2]),
                        "y2": int(xyxy[3]),
                        "confidence": conf,
                    })

            self.latest_tracks = tracks

            # Update target seen time
            if self.target_track_id is not None:
                for t in tracks:
                    if t["track_id"] == self.target_track_id:
                        self.target_last_seen_time = time.time()
                        break

            # ---------------------------------------------------------
            # Publish Follow Target Message
            # ---------------------------------------------------------
            target_msg = TargetPerson()
            target_msg.header = header
            target_msg.target_locked = False
            target_msg.track_id = -1
            target_msg.x1 = 0.0
            target_msg.y1 = 0.0
            target_msg.x2 = 0.0
            target_msg.y2 = 0.0
            target_msg.confidence = 0.0

            if self.target_track_id is not None:
                for t in tracks:
                    if t["track_id"] == self.target_track_id:
                        target_msg.target_locked = True
                        target_msg.track_id = t["track_id"]
                        target_msg.x1 = float(t["x1"])
                        target_msg.y1 = float(t["y1"])
                        target_msg.x2 = float(t["x2"])
                        target_msg.y2 = float(t["y2"])
                        target_msg.confidence = t["confidence"]
                        break

            self.target_pub.publish(target_msg)

            # FPS
            self.fps_count += 1
            elapsed = time.time() - self.fps_start
            if elapsed >= 5.0:
                fps = self.fps_count / elapsed
                self.get_logger().info(
                    f"Follow YOLO FPS: {fps:.1f} | "
                    f"Persons: {len(tracks)} | "
                    f"State: {self.state.value}"
                )
                self.fps_count = 0
                self.fps_start = time.time()

            # Publish debug image at reduced rate (every 3rd inference)
            if self.fps_count % 3 == 0:
                self._publish_debug(frame, tracks)

            # Small sleep to prevent 100% CPU lock in tight loop
            time.sleep(0.005)

    # =============================================================
    # CONTROL LOOP (10 Hz)
    # =============================================================

    def control_loop(self):
        """Main state machine and controller."""

        now = time.time()

        # -------------------------------------------------------
        # IDLE
        # -------------------------------------------------------

        if self.state == FollowState.IDLE:
            self._publish_zero_vel()
            return

        # -------------------------------------------------------
        # STOPPED
        # -------------------------------------------------------

        if self.state == FollowState.STOPPED:
            self._publish_zero_vel()

            # Re-enter waiting if auth still valid
            if (self.latest_auth
                    and not self.latest_auth.authenticated):
                self.state = FollowState.WAITING_FOR_AUTH
            return

        # -------------------------------------------------------
        # WAITING_FOR_AUTH
        # -------------------------------------------------------

        if self.state == FollowState.WAITING_FOR_AUTH:
            self._publish_zero_vel()

            if (self.latest_auth
                    and self.latest_auth.authenticated):
                self.authenticated_username = (
                    self.latest_auth.username
                )
                self.auth_face_id = self.latest_auth.face_id
                self.state = FollowState.TARGET_ACQUISITION
                self.get_logger().info(
                    f"Auth detected: {self.authenticated_username}"
                    f" → TARGET_ACQUISITION"
                )
            return

        # -------------------------------------------------------
        # Check auth is still valid (for all active states)
        # -------------------------------------------------------

        if (self.latest_auth is None
                or not self.latest_auth.authenticated):
            self.get_logger().warning(
                "Auth lost → STOPPED"
            )
            self._stop_following()
            self.state = FollowState.STOPPED
            self._publish_zero_vel()
            return

        # -------------------------------------------------------
        # TARGET_ACQUISITION
        # -------------------------------------------------------

        if self.state == FollowState.TARGET_ACQUISITION:
            self._publish_zero_vel()
            self._attempt_target_acquisition()
            return

        # -------------------------------------------------------
        # FOLLOWING
        # -------------------------------------------------------

        if self.state == FollowState.FOLLOWING:
            self._follow_target(now)
            return

        # -------------------------------------------------------
        # TARGET_LOST
        # -------------------------------------------------------

        if self.state == FollowState.TARGET_LOST:
            self._publish_zero_vel()

            if self.target_lost_time == 0.0:
                self.target_lost_time = now

            elapsed = now - self.target_lost_time

            if elapsed >= self.target_lost_timeout:
                self.state = FollowState.REACQUIRE
                self.get_logger().info(
                    "Target lost timeout → REACQUIRE"
                )
            return

        # -------------------------------------------------------
        # REACQUIRE
        # -------------------------------------------------------

        if self.state == FollowState.REACQUIRE:
            self._publish_zero_vel()

            # Check if target has returned
            target = self._find_target_in_tracks()
            if target is not None:
                self.get_logger().info(
                    f"Target reacquired (track_id="
                    f"{self.target_track_id}) → FOLLOWING"
                )
                self.state = FollowState.FOLLOWING
                self.target_lost_time = 0.0
                return

            # Timeout → require new auth association
            if self.target_lost_time > 0.0:
                elapsed = now - self.target_lost_time
                if elapsed >= self.reacquire_timeout:
                    self.get_logger().warning(
                        "Reacquire timeout → "
                        "TARGET_ACQUISITION"
                    )
                    self._stop_following()
                    self.state = FollowState.TARGET_ACQUISITION
            return

    # =============================================================
    # TARGET ACQUISITION
    # =============================================================

    def _attempt_target_acquisition(self):
        """Associate authenticated face with a person track."""

        # Need face detections and person tracks
        if (self.latest_face_detections is None
                or len(self.latest_tracks) == 0):
            return

        # Find the authenticated face bbox
        auth_face = None
        for face in self.latest_face_detections.faces:
            if face.id == self.auth_face_id:
                auth_face = face
                break

        if auth_face is None:
            # Try any face if only one is detected
            if len(self.latest_face_detections.faces) == 1:
                auth_face = self.latest_face_detections.faces[0]
            else:
                return

        # Face center
        face_cx = auth_face.x + auth_face.width / 2.0
        face_cy = auth_face.y + auth_face.height / 2.0

        # Find person track containing the face center
        candidates = []

        for track in self.latest_tracks:
            if (track["x1"] <= face_cx <= track["x2"]
                    and track["y1"] <= face_cy <= track["y2"]):
                candidates.append(track)

        if len(candidates) == 0:
            # Fallback: find closest person bbox to face center
            return

        if len(candidates) > 1:
            # Ambiguous — fail closed
            self.get_logger().warning(
                f"Multiple person tracks ({len(candidates)}) "
                f"contain the face — not acquiring",
                throttle_duration_sec=3.0
            )
            return

        # Exactly one match
        target = candidates[0]
        self.target_track_id = target["track_id"]
        self.target_last_seen_time = time.time()
        self.target_lost_time = 0.0
        self.state = FollowState.FOLLOWING

        self.get_logger().info(
            f"Target acquired: "
            f"user={self.authenticated_username} → "
            f"track_id={self.target_track_id}"
        )

    # =============================================================
    # FOLLOWING
    # =============================================================

    def _follow_target(self, now):
        """Track and follow the target person."""

        target = self._find_target_in_tracks()

        if target is None:
            # Target not in current frame
            time_since = now - self.target_last_seen_time
            if time_since >= self.target_lost_timeout:
                self.get_logger().warning(
                    f"Target track_id={self.target_track_id} "
                    f"lost for {time_since:.1f}s → TARGET_LOST"
                )
                self.state = FollowState.TARGET_LOST
                self.target_lost_time = now
            self._publish_zero_vel()
            return

        # ---------------------------------------------------------
        # Target found — calculate control
        # ---------------------------------------------------------

        # Target center in image
        target_cx = (target["x1"] + target["x2"]) / 2.0
        target_cy = (target["y1"] + target["y2"]) / 2.0

        image_center_x = self.image_width / 2.0

        # Horizontal error (pixels)
        error_x = target_cx - image_center_x

        # ---------------------------------------------------------
        # Angular control
        # ---------------------------------------------------------

        if abs(error_x) < self.horizontal_deadzone:
            angular_z = 0.0
        else:
            # Negative because positive angular_z = left turn,
            # but positive error_x = target is to the right
            angular_z = -self.Kp_angular * error_x

        angular_z = self._clamp(
            angular_z,
            -self.max_angular_speed,
            self.max_angular_speed
        )

        # ---------------------------------------------------------
        # LiDAR distance
        # ---------------------------------------------------------

        target_distance = self._get_lidar_distance(
            target_cx
        )

        if target_distance is None:
            # No valid LiDAR — stop
            self._publish_zero_vel()
            return

        # ---------------------------------------------------------
        # Linear control
        # ---------------------------------------------------------

        # Emergency stop
        if target_distance < self.emergency_distance:
            self._publish_zero_vel()
            return

        # Too close — stop
        if target_distance < self.min_follow_distance:
            linear_x = 0.0
        else:
            distance_error = (
                target_distance - self.desired_distance
            )
            linear_x = self.Kp_linear * distance_error

        linear_x = self._clamp(
            linear_x,
            -self.max_linear_speed,
            self.max_linear_speed
        )

        # ---------------------------------------------------------
        # Rotation priority: slow forward if turning hard
        # ---------------------------------------------------------

        if abs(error_x) > self.rotation_slowdown_threshold:
            linear_x *= 0.3

        # ---------------------------------------------------------
        # Safety: check for frontal obstacles
        # ---------------------------------------------------------

        if self._frontal_obstacle_detected():
            linear_x = 0.0

        # ---------------------------------------------------------
        # Publish cmd_vel
        # ---------------------------------------------------------

        twist = Twist()
        twist.linear.x = float(linear_x)
        twist.angular.z = float(angular_z)
        self.cmd_vel_pub.publish(twist)

    # =============================================================
    # LIDAR DISTANCE
    # =============================================================

    def _get_lidar_distance(self, target_pixel_x):
        """
        Get distance to target using LiDAR.

        Converts the target's camera pixel position to an angle,
        then samples the corresponding LiDAR sector.
        """

        if self.latest_scan is None:
            return None

        scan = self.latest_scan

        # Convert pixel position to camera-relative angle
        # Left of center = positive angle
        image_center = self.image_width / 2.0
        pixel_offset = target_pixel_x - image_center

        # Camera FOV to radians
        hfov_rad = math.radians(self.camera_hfov_deg)

        # Pixel offset to angle
        # Negative because camera right = lidar left convention
        target_angle_rad = -(
            pixel_offset / image_center
        ) * (hfov_rad / 2.0)

        # LiDAR angular window
        window_rad = math.radians(
            self.lidar_angle_window_deg
        )

        angle_min_search = target_angle_rad - window_rad / 2.0
        angle_max_search = target_angle_rad + window_rad / 2.0

        # Collect valid ranges in the angular window
        valid_ranges = []

        for i, r in enumerate(scan.ranges):
            angle = scan.angle_min + i * scan.angle_increment

            if angle_min_search <= angle <= angle_max_search:
                if (not math.isnan(r)
                        and not math.isinf(r)
                        and r > 0.05
                        and r < scan.range_max):
                    valid_ranges.append(r)

        if len(valid_ranges) == 0:
            return None

        # Use median for robustness
        distance = float(np.median(valid_ranges))

        return distance

    # =============================================================
    # SAFETY
    # =============================================================

    def _frontal_obstacle_detected(self):
        """Check for obstacles directly in front."""

        if self.latest_scan is None:
            return True  # Fail safe

        scan = self.latest_scan

        # Check a narrow frontal cone (±15°)
        frontal_window = math.radians(15.0)

        for i, r in enumerate(scan.ranges):
            angle = scan.angle_min + i * scan.angle_increment

            if abs(angle) <= frontal_window:
                if (not math.isnan(r)
                        and not math.isinf(r)
                        and r > 0.01
                        and r < self.emergency_distance):
                    return True

        return False

    # =============================================================
    # HELPERS
    # =============================================================

    def _find_target_in_tracks(self):
        """Find the target track_id in current tracks."""
        if self.target_track_id is None:
            return None

        for t in self.latest_tracks:
            if t["track_id"] == self.target_track_id:
                return t

        return None

    def _stop_following(self):
        """Clear target state."""
        self.target_track_id = None
        self.authenticated_username = ""
        self.auth_face_id = -1
        self.target_lost_time = 0.0

    def _publish_zero_vel(self):
        """Publish zero velocity."""
        twist = Twist()
        self.cmd_vel_pub.publish(twist)

    @staticmethod
    def _clamp(value, min_val, max_val):
        return max(min_val, min(value, max_val))

    # =============================================================
    # DEBUG IMAGE
    # =============================================================

    def _publish_debug(self, frame, tracks):
        """Publish annotated debug image."""

        debug = frame.copy()

        target = self._find_target_in_tracks()

        # Draw all person tracks
        for t in tracks:
            is_target = (
                self.target_track_id is not None
                and t["track_id"] == self.target_track_id
            )

            color = (0, 255, 0) if is_target else (128, 128, 128)
            thickness = 3 if is_target else 1

            cv2.rectangle(
                debug,
                (t["x1"], t["y1"]),
                (t["x2"], t["y2"]),
                color,
                thickness,
            )

            label = f"T{t['track_id']} {t['confidence']:.2f}"
            if is_target:
                label = (
                    f"TARGET: {self.authenticated_username} "
                    f"T{t['track_id']}"
                )

            cv2.putText(
                debug,
                label,
                (t["x1"], max(20, t["y1"] - 10)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                color,
                2,
            )

        # Target center marker
        if target is not None:
            cx = int((target["x1"] + target["x2"]) / 2)
            cy = int((target["y1"] + target["y2"]) / 2)
            cv2.circle(debug, (cx, cy), 8, (0, 0, 255), -1)
            cv2.line(
                debug,
                (cx - 15, cy), (cx + 15, cy),
                (0, 0, 255), 2
            )
            cv2.line(
                debug,
                (cx, cy - 15), (cx, cy + 15),
                (0, 0, 255), 2
            )

        # State + distance overlay
        state_text = f"STATE: {self.state.value}"

        distance_text = ""
        if target is not None:
            tcx = (target["x1"] + target["x2"]) / 2.0
            dist = self._get_lidar_distance(tcx)
            if dist is not None:
                distance_text = f"DIST: {dist:.2f}m"

        cv2.putText(
            debug,
            state_text,
            (10, 30),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.8,
            (0, 255, 255),
            2,
        )

        if distance_text:
            cv2.putText(
                debug,
                distance_text,
                (10, 60),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.8,
                (0, 255, 255),
                2,
            )

        target_text = (
            f"TARGET: {self.authenticated_username} "
            f"(T{self.target_track_id})"
            if self.target_track_id is not None
            else "TARGET: None"
        )

        cv2.putText(
            debug,
            target_text,
            (10, 90),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            (0, 255, 255),
            2,
        )

        # Publish
        try:
            debug_msg = self.bridge.cv2_to_imgmsg(
                debug, encoding="bgr8"
            )
            self.debug_pub.publish(debug_msg)
        except Exception:
            pass

    # =============================================================
    # CLEANUP
    # =============================================================

    def destroy_node(self):
        self._publish_zero_vel()
        super().destroy_node()


# =================================================================
# MAIN
# =================================================================

from rclpy.executors import MultiThreadedExecutor

def main(args=None):
    rclpy.init(args=args)
    node = HumanFollowNode()
    executor = MultiThreadedExecutor(num_threads=4)
    executor.add_node(node)
    try:
        executor.spin()
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()

if __name__ == "__main__":
    main()
