import rclpy
from rclpy.node import Node
from sensor_msgs.msg import Image
from cv_bridge import CvBridge
from rclpy.qos import qos_profile_sensor_data
import cv2
import time
import numpy as np
import threading
import torch

from aura_follow_msgs.msg import TargetPerson
from aura_face_msgs.msg import AuthenticationStatus
from aura_behavior_msgs.msg import BehaviorState, BehaviorEvent

from .pose_estimator import PoseEstimator
from .temporal_buffer import TemporalBuffer
from .utils import extract_keypoints, calculate_features
from .behavior_classifier import BehaviorClassifier
from .fall_detector import FallDetector


class BehaviorNode(Node):
    def __init__(self):
        super().__init__('behavior_node')

        # Limit PyTorch CPU threads for YOLO to avoid contention
        torch.set_num_threads(2)

        # ---------------------------------------------------------
        # Parameters
        # ---------------------------------------------------------
        self.declare_parameter("pose_model", "yolo11n-pose.pt")
        self.declare_parameter("pose_imgsz", 320)
        self.declare_parameter("pose_confidence_threshold", 0.5)
        self.declare_parameter("process_every_n_frames", 2)
        self.declare_parameter("temporal_buffer_size", 30)
        self.declare_parameter("behavior_history_seconds", 1.0)
        self.declare_parameter("fall_verification_seconds", 2.0)
        self.declare_parameter("target_lost_timeout", 1.0)

        self.declare_parameter("walking_min_movement", 8.0)
        self.declare_parameter("fall_min_vertical_velocity", 150.0)
        self.declare_parameter("fall_body_angle_threshold", 50.0)
        self.declare_parameter("lying_body_angle_threshold", 55.0)
        self.declare_parameter("low_movement_threshold", 10.0)
        self.declare_parameter("event_cooldown_seconds", 10.0)
        self.declare_parameter("debug_publish", True)
        self.declare_parameter("debug_publish_every_n", 3)
        self.declare_parameter("behavior_confirmation_frames", 3)
        self.declare_parameter("min_valid_keypoints", 3)
        self.declare_parameter("max_frame_age_ms", 150.0)
        self.declare_parameter("perf_logging", True)

        # Extract params into a dict for modules
        self.params = {
            'walking_min_movement': self.get_parameter("walking_min_movement").value,
            'fall_min_vertical_velocity': self.get_parameter("fall_min_vertical_velocity").value,
            'fall_body_angle_threshold': self.get_parameter("fall_body_angle_threshold").value,
            'lying_body_angle_threshold': self.get_parameter("lying_body_angle_threshold").value,
            'low_movement_threshold': self.get_parameter("low_movement_threshold").value,
            'event_cooldown_seconds': self.get_parameter("event_cooldown_seconds").value,
            'fall_verification_seconds': self.get_parameter("fall_verification_seconds").value,
            'behavior_confirmation_frames': self.get_parameter("behavior_confirmation_frames").value,
            'min_valid_keypoints': self.get_parameter("min_valid_keypoints").value,
        }

        # ---------------------------------------------------------
        # State
        # ---------------------------------------------------------
        self.authenticated = False
        self.target = None
        self.target_last_seen = 0.0
        self.frame_count = 0
        self.process_every_n = self.get_parameter("process_every_n_frames").value
        self.debug_every_n = self.get_parameter("debug_publish_every_n").value
        self.debug_count = 0
        self.perf_logging = self.get_parameter("perf_logging").value

        # FPS tracking
        self.fps_count = 0
        self.fps_start = time.time()

        # Performance accumulators
        self.perf_pose_total = 0.0
        self.perf_classify_total = 0.0
        self.perf_debug_total = 0.0
        self.perf_frame_age_total = 0.0
        self.perf_e2e_total = 0.0
        self.perf_count = 0

        # ---------------------------------------------------------
        # Modules
        # ---------------------------------------------------------
        behavior_history_s = self.get_parameter("behavior_history_seconds").value
        self.pose_estimator = PoseEstimator(
            model_path=self.get_parameter("pose_model").value,
            imgsz=self.get_parameter("pose_imgsz").value,
            conf_thresh=self.get_parameter("pose_confidence_threshold").value
        )
        self.temporal_buffer = TemporalBuffer(
            size=self.get_parameter("temporal_buffer_size").value,
            max_age_seconds=behavior_history_s
        )
        self.classifier = BehaviorClassifier(self.params)
        self.fall_detector = FallDetector(self.params)

        self.bridge = CvBridge()

        # ---------------------------------------------------------
        # Publishers
        # ---------------------------------------------------------
        self.state_pub = self.create_publisher(BehaviorState, '/behavior/state', 10)
        self.event_pub = self.create_publisher(BehaviorEvent, '/behavior/event', 10)
        self.debug_pub = self.create_publisher(Image, '/behavior/debug', 10)

        # ---------------------------------------------------------
        # Subscribers
        # ---------------------------------------------------------
        self.auth_sub = self.create_subscription(
            AuthenticationStatus,
            "/auth/status",
            self.auth_callback,
            10
        )

        self.target_sub = self.create_subscription(
            TargetPerson,
            "/follow/target",
            self.target_callback,
            10
        )

        self.image_sub = self.create_subscription(
            Image,
            "/camera/image_raw",
            self.image_callback,
            qos_profile_sensor_data
        )

        # ---------------------------------------------------------
        # Async inference setup
        # ---------------------------------------------------------
        self.latest_frame = None
        self.latest_header = None
        self.last_processed_stamp = None
        self.latest_keypoints = None
        self.latest_bbox = None
        self.latest_behavior_str = "UNKNOWN"
        self.latest_behavior_conf = 0.0

        self.inference_thread = threading.Thread(target=self.inference_loop, daemon=True)
        self.inference_thread.start()

        self.get_logger().info("Behavior node initialized.")

    # =============================================================
    # CALLBACKS
    # =============================================================

    def auth_callback(self, msg):
        was_auth = self.authenticated
        self.authenticated = msg.authenticated

        if not self.authenticated and was_auth:
            self.get_logger().warning("Auth lost -> pausing behavior processing")

    def target_callback(self, msg):
        now = time.time()
        if msg.target_locked:
            self.target = msg
            self.target_last_seen = now
        else:
            if now - self.target_last_seen > self.get_parameter("target_lost_timeout").value:
                self.target = None
                self._reset_state()

    def _reset_state(self):
        self.temporal_buffer.clear()
        self.fall_detector.reset()
        self.classifier.reset()

    def image_callback(self, msg):
        try:
            frame = self.bridge.imgmsg_to_cv2(msg, desired_encoding="bgr8")
        except Exception as e:
            self.get_logger().error(f"CV bridge error: {e}")
            return

        self.latest_frame = frame
        self.latest_header = msg.header

    # =============================================================
    # INFERENCE LOOP
    # =============================================================

    def inference_loop(self):
        while rclpy.ok():
            if self.latest_frame is None or self.latest_header is None:
                time.sleep(0.005)
                continue

            # Frame dropping: only process new frames
            if self.last_processed_stamp == self.latest_header.stamp:
                time.sleep(0.005)
                continue
            self.last_processed_stamp = self.latest_header.stamp

            self.frame_count += 1
            if self.frame_count % self.process_every_n != 0:
                continue

            # State-aware: skip AI when not authenticated or no target
            if not self.authenticated or self.target is None:
                # Publish debug at reduced rate so video doesn't freeze
                self.debug_count += 1
                if self.get_parameter("debug_publish").value and self.debug_count % self.debug_every_n == 0:
                    self._publish_debug(self.latest_frame, None, None, "UNKNOWN", 0.0)
                # Reset FPS timer so it doesn't count idle time
                self.fps_start = time.time()
                self.fps_count = 0
                time.sleep(0.005)
                continue

            # Grab the latest frame and target
            frame = self.latest_frame
            header = self.latest_header
            
            # Calculate frame age
            frame_time = header.stamp.sec + header.stamp.nanosec * 1e-9
            now = self.get_clock().now().nanoseconds * 1e-9
            frame_age_ms = (now - frame_time) * 1000.0
            
            if frame_age_ms > self.get_parameter("max_frame_age_ms").value:
                # Discard stale frame
                self.get_logger().warning(f"Discarding stale frame (age: {frame_age_ms:.1f} ms)")
                time.sleep(0.005)
                continue

            bbox = [self.target.x1, self.target.y1, self.target.x2, self.target.y2]

            loop_start = time.time()

            # 1. Pose estimation (timed)
            t0 = time.time()
            keypoints = self.pose_estimator.estimate_pose(frame, bbox)
            pose_ms = (time.time() - t0) * 1000.0

            behavior_str = "UNKNOWN"
            behavior_conf = 0.0

            if keypoints is not None:
                # 2. Feature extraction + classification (timed)
                t1 = time.time()
                pts = extract_keypoints(keypoints)
                features = calculate_features(pts, bbox)

                if features['valid']:
                    self.temporal_buffer.append(features)

                    # 3. Classify behavior
                    history = self.temporal_buffer.get_recent()
                    behavior_str, behavior_conf = self.classifier.classify(history)

                    # 4. Fall detection (separate temporal window)
                    event_type = self.fall_detector.update(history)
                    if event_type:
                        self._publish_event(event_type, behavior_str, behavior_conf)
                        if event_type == "FALL_SUSPECTED" and self.fall_detector.state != "NORMAL":
                            behavior_str = "FALL"

                classify_ms = (time.time() - t1) * 1000.0
            else:
                classify_ms = 0.0

            if self.fall_detector.state == "FALL_CONFIRMED" or self.fall_detector.state == "VERIFYING":
                behavior_str = "FALL"

            self.latest_keypoints = keypoints
            self.latest_bbox = bbox
            self.latest_behavior_str = behavior_str
            self.latest_behavior_conf = behavior_conf

            # 5. Publish State
            state_msg = BehaviorState()
            state_msg.header = header
            state_msg.behavior = behavior_str
            state_msg.confidence = behavior_conf
            state_msg.fall_suspected = (self.fall_detector.state in ["FALL_SUSPECTED", "VERIFYING"])
            state_msg.fall_confirmed = (self.fall_detector.state == "FALL_CONFIRMED")
            self.state_pub.publish(state_msg)

            # 6. Debug image at reduced rate
            t2 = time.time()
            self.debug_count += 1
            if self.get_parameter("debug_publish").value and self.debug_count % self.debug_every_n == 0:
                self._publish_debug(frame, keypoints, bbox, behavior_str, behavior_conf)
            debug_ms = (time.time() - t2) * 1000.0

            loop_ms = (time.time() - loop_start) * 1000.0

            # Measure end-to-end latency (age of frame at publication)
            pub_now = self.get_clock().now().nanoseconds * 1e-9
            e2e_latency_ms = (pub_now - frame_time) * 1000.0

            # Perf accumulation
            self.perf_pose_total += pose_ms
            self.perf_classify_total += classify_ms
            self.perf_debug_total += debug_ms
            self.perf_frame_age_total += frame_age_ms
            self.perf_e2e_total += e2e_latency_ms
            self.perf_count += 1

            # FPS + perf logging
            self.fps_count += 1
            elapsed = time.time() - self.fps_start
            if elapsed >= 5.0:
                fps = self.fps_count / elapsed
                log_msg = (
                    f"Behavior FPS: {fps:.1f} | "
                    f"Behavior: {behavior_str}"
                )
                if self.perf_logging and self.perf_count > 0:
                    avg_pose = self.perf_pose_total / self.perf_count
                    avg_cls = self.perf_classify_total / self.perf_count
                    avg_dbg = self.perf_debug_total / self.perf_count
                    avg_age = self.perf_frame_age_total / self.perf_count
                    avg_e2e = self.perf_e2e_total / self.perf_count
                    log_msg += (
                        f" | [PERF] age={avg_age:.0f}ms "
                        f"pose={avg_pose:.0f}ms "
                        f"classify={avg_cls:.0f}ms "
                        f"debug={avg_dbg:.0f}ms "
                        f"e2e={avg_e2e:.0f}ms"
                    )
                self.get_logger().info(log_msg)
                self.fps_count = 0
                self.fps_start = time.time()
                self.perf_pose_total = 0.0
                self.perf_classify_total = 0.0
                self.perf_debug_total = 0.0
                self.perf_frame_age_total = 0.0
                self.perf_e2e_total = 0.0
                self.perf_count = 0

    # =============================================================
    # EVENT PUBLISHING
    # =============================================================

    def _publish_event(self, event_type, behavior, confidence):
        event_msg = BehaviorEvent()
        event_msg.header = self.get_clock().now().to_msg()
        event_msg.event_type = event_type
        event_msg.behavior = behavior
        event_msg.confidence = confidence
        event_msg.target_track_id = self.target.track_id if self.target else -1

        if event_type == "FALL_CONFIRMED":
            event_msg.severity = "HIGH"
            event_msg.requires_attention = True
        elif event_type == "FALL_SUSPECTED":
            event_msg.severity = "MEDIUM"
            event_msg.requires_attention = False
        else:
            event_msg.severity = "NORMAL"
            event_msg.requires_attention = False

        self.event_pub.publish(event_msg)
        self.get_logger().info(f"Published BehaviorEvent: {event_type}")

    # =============================================================
    # DEBUG IMAGE
    # =============================================================

    def _publish_debug(self, frame, keypoints, bbox, behavior_str, behavior_conf):
        debug_frame = frame.copy()

        # Draw bbox
        if bbox:
            x1, y1, x2, y2 = [int(v) for v in bbox]
            cv2.rectangle(debug_frame, (x1, y1), (x2, y2), (0, 255, 0), 2)

        # Draw keypoints
        if keypoints is not None:
            for pt in keypoints:
                if pt[2] > 0.3:
                    cv2.circle(debug_frame, (int(pt[0]), int(pt[1])), 4, (0, 0, 255), -1)

        # Overlay text
        cv2.putText(debug_frame, f"TARGET: AUTHENTICATED", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)
        cv2.putText(debug_frame, f"BEHAVIOR: {behavior_str}", (10, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)
        cv2.putText(debug_frame, f"SCORE: {behavior_conf:.2f}", (10, 90), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)

        fall_status = "NO"
        if self.fall_detector.state == "VERIFYING":
            fall_status = "VERIFYING"
        elif self.fall_detector.state == "FALL_CONFIRMED":
            fall_status = "CONFIRMED"

        cv2.putText(debug_frame, f"FALL: {fall_status}", (10, 120), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255) if fall_status != "NO" else (0, 255, 255), 2)

        self.debug_pub.publish(self.bridge.cv2_to_imgmsg(debug_frame, encoding="bgr8"))


from rclpy.executors import MultiThreadedExecutor

def main(args=None):
    rclpy.init(args=args)
    node = BehaviorNode()
    executor = MultiThreadedExecutor(num_threads=4)
    executor.add_node(node)
    try:
        executor.spin()
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()

if __name__ == '__main__':
    main()
