#!/usr/bin/env python3
"""AURA semantic mapping prototype.

This node listens to the camera stream, runs a lightweight YOLO object detector,
aggregates recent detections over a 5-second window, infers a probable room,
and publishes a compact JSON summary for downstream semantic mapping.

The intent is to keep the prototype lightweight and separate from the existing
robot follow and SLAM stack, while still creating a useful demo-ready semantic
layer.
"""

import json
import os
import time
from collections import Counter, defaultdict, deque
from threading import Lock

import cv2
import numpy as np

import rclpy
from cv_bridge import CvBridge
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import Image
from std_msgs.msg import String
from ultralytics import YOLO


class SemanticMapper(Node):
    """Collects object detections into a semantic scene summary."""

    ROOM_HINTS = {
        'bed': 'bedroom',
        'pillow': 'bedroom',
        'sofa': 'living_room',
        'tv': 'living_room',
        'couch': 'living_room',
        'chair': 'dining_room',
        'dining table': 'dining_room',
        'table': 'dining_room',
        'toilet': 'bathroom',
        'sink': 'bathroom',
        'refrigerator': 'kitchen',
        'microwave': 'kitchen',
        'oven': 'kitchen',
        'desk': 'office',
        'laptop': 'office',
        'person': 'entrance',
    }

    def __init__(self):
        super().__init__('semantic_mapper')

        self.declare_parameter('camera_topic', '/camera/image')
        self.declare_parameter('camera_frame_id', 'camera')
        self.declare_parameter('model_path', 'yolov8n.pt')
        self.declare_parameter('confidence_threshold', 0.35)
        self.declare_parameter('process_every_n_frames', 2)
        self.declare_parameter('observation_window_sec', 5.0)
        self.declare_parameter('summary_topic', '/semantic_map/summary')
        self.declare_parameter('debug_image_topic', '/semantic_map/debug')

        self.camera_topic = self.get_parameter('camera_topic').value
        self.model_path = self.get_parameter('model_path').value
        self.confidence_threshold = float(
            self.get_parameter('confidence_threshold').value
        )
        self.process_every_n_frames = int(
            self.get_parameter('process_every_n_frames').value
        )
        self.observation_window_sec = float(
            self.get_parameter('observation_window_sec').value
        )
        self.summary_topic = self.get_parameter('summary_topic').value
        self.debug_image_topic = self.get_parameter('debug_image_topic').value

        self.bridge = CvBridge()
        self.latest_frame = None
        self.latest_detections = []
        self.frame_counter = 0
        self._lock = Lock()
        self.recent_observations = deque()

        self.get_logger().info('Loading YOLO model for semantic mapping...')
        self.model = self._load_model()
        self.get_logger().info('Semantic mapper ready.')

        self.image_sub = self.create_subscription(
            Image,
            self.camera_topic,
            self.image_callback,
            qos_profile_sensor_data,
        )

        self.summary_pub = self.create_publisher(String, self.summary_topic, 10)
        self.debug_pub = self.create_publisher(Image, self.debug_image_topic, 10)

        self.aggregate_timer = self.create_timer(1.0, self.publish_semantic_summary)

    def _load_model(self):
        """Load a lightweight COCO detector if available."""
        candidates = [
            self.model_path,
            os.path.basename(self.model_path),
            'yolov8n.pt',
            'yolo11n.pt',
        ]

        search_roots = [
            os.getcwd(),
            os.path.expanduser('~/AURA_WS3'),
            os.path.expanduser('~'),
            os.path.dirname(os.path.abspath(__file__)),
        ]

        for candidate in candidates:
            if not candidate:
                continue
            if os.path.isabs(candidate) and os.path.isfile(candidate):
                return YOLO(candidate)

            for root in search_roots:
                if not root:
                    continue
                for test_path in [
                    os.path.abspath(os.path.join(root, candidate)),
                    os.path.abspath(os.path.join(root, os.path.basename(candidate))),
                ]:
                    if os.path.isfile(test_path):
                        return YOLO(test_path)

        self.get_logger().warn(
            'Model file not found locally; ulralytics may download it automatically.'
        )
        return YOLO(self.model_path)

    def image_callback(self, msg: Image):
        try:
            frame = self.bridge.imgmsg_to_cv2(msg, desired_encoding='bgr8')
        except Exception as exc:  # pragma: no cover - ROS conversion errors
            self.get_logger().warning(f'Image conversion failed: {exc}')
            return

        self.frame_counter += 1
        if self.frame_counter % self.process_every_n_frames != 0:
            return

        with self._lock:
            self.latest_frame = frame.copy()

        self._run_detection(frame)

    def _run_detection(self, frame):
        if frame is None:
            return

        try:
            results = self.model(frame, conf=self.confidence_threshold, verbose=False)
        except Exception as exc:  # pragma: no cover - model/runtime errors
            self.get_logger().warning(f'Detection failed: {exc}')
            return

        if not results or len(results) == 0:
            return

        result = results[0]
        boxes = result.boxes
        if boxes is None or len(boxes) == 0:
            return

        detections = []
        for box in boxes:
            try:
                conf = float(box.conf.item())
                cls_id = int(box.cls.item())
            except Exception:
                continue

            if conf < self.confidence_threshold:
                continue

            label = self.model.names.get(cls_id, str(cls_id)).lower()
            x1, y1, x2, y2 = map(float, box.xyxy[0].tolist())
            detections.append({
                'label': label,
                'confidence': conf,
                'bbox': [x1, y1, x2, y2],
                'timestamp': time.time(),
            })

        self.latest_detections = detections
        for item in detections:
            self.recent_observations.append(item)

        self._trim_observations()

    def _trim_observations(self):
        cutoff = time.time() - self.observation_window_sec
        while self.recent_observations and self.recent_observations[0]['timestamp'] < cutoff:
            self.recent_observations.popleft()

    def _infer_room(self, label_counts):
        if not label_counts:
            return 'unknown', 0.0

        room_scores = defaultdict(float)
        for label, count in label_counts.items():
            room = self.ROOM_HINTS.get(label)
            if room is None:
                continue
            room_scores[room] += count

        if not room_scores:
            return 'unknown', 0.0

        room_name, score = max(room_scores.items(), key=lambda item: item[1])
        confidence = min(1.0, score / max(1, sum(label_counts.values())))
        return room_name, confidence

    def publish_semantic_summary(self):
        if not self.recent_observations:
            return

        self._trim_observations()

        label_counts = Counter()
        for item in self.recent_observations:
            label_counts[item['label']] += 1

        room_name, room_confidence = self._infer_room(label_counts)
        top_labels = [
            {'label': label, 'count': count}
            for label, count in label_counts.most_common(5)
        ]

        payload = {
            'room': room_name,
            'room_confidence': round(room_confidence, 3),
            'window_sec': self.observation_window_sec,
            'objects': top_labels,
            'timestamp': time.time(),
        }

        msg = String()
        msg.data = json.dumps(payload)
        self.summary_pub.publish(msg)

        debug_frame = None
        with self._lock:
            if self.latest_frame is not None:
                debug_frame = self.latest_frame.copy()

        if debug_frame is not None and self.debug_pub.get_subscription_count() > 0:
            overlay = debug_frame.copy()
            for item in self.latest_detections:
                x1, y1, x2, y2 = [int(v) for v in item['bbox']]
                cv2.rectangle(overlay, (x1, y1), (x2, y2), (0, 255, 0), 2)
                cv2.putText(
                    overlay,
                    item['label'],
                    (x1, max(0, y1 - 8)),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.5,
                    (0, 255, 0),
                    2,
                )
            debug_image_msg = self.bridge.cv2_to_imgmsg(overlay, encoding='bgr8')
            self.debug_pub.publish(debug_image_msg)


def main(args=None):
    rclpy.init(args=args)
    node = SemanticMapper()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
