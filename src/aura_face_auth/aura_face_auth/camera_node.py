#!/usr/bin/env python3

import time

import cv2
import rclpy
from rclpy.node import Node
from sensor_msgs.msg import Image
from cv_bridge import CvBridge


class CameraNode(Node):

    def __init__(self):
        super().__init__("camera_node")

        # ---------------------------------------------------------
        # ROS 2 parameters
        # ---------------------------------------------------------

        self.declare_parameter("camera_index", 0)
        self.declare_parameter("frame_width", 640)
        self.declare_parameter("frame_height", 480)
        self.declare_parameter("fps", 30)

        self.camera_index = self.get_parameter(
            "camera_index"
        ).value

        self.frame_width = self.get_parameter(
            "frame_width"
        ).value

        self.frame_height = self.get_parameter(
            "frame_height"
        ).value

        self.fps = self.get_parameter("fps").value

        # ---------------------------------------------------------
        # Publisher
        # ---------------------------------------------------------

        self.publisher = self.create_publisher(
            Image,
            "/camera/image_raw",
            10
        )

        self.bridge = CvBridge()

        # ---------------------------------------------------------
        # Open camera
        # ---------------------------------------------------------

        self.cap = None
        self._open_camera()

        # ---------------------------------------------------------
        # Timer
        # ---------------------------------------------------------

        timer_period = 1.0 / self.fps

        self.timer = self.create_timer(
            timer_period,
            self.publish_frame
        )

        # ---------------------------------------------------------
        # FPS tracking
        # ---------------------------------------------------------

        self.frame_count = 0
        self.fps_start_time = time.time()
        self.fps_log_interval = 5.0  # seconds

        self.get_logger().info(
            f"Camera Node started | "
            f"index={self.camera_index} "
            f"resolution={self.frame_width}x{self.frame_height} "
            f"target_fps={self.fps}"
        )

    # =============================================================
    # OPEN CAMERA
    # =============================================================

    def _open_camera(self):
        """Open the camera with configured parameters."""

        if self.cap is not None:
            self.cap.release()

        self.cap = cv2.VideoCapture(self.camera_index)

        if not self.cap.isOpened():
            self.get_logger().error(
                f"Cannot open camera at index {self.camera_index}"
            )
            raise RuntimeError(
                f"Camera not found at index {self.camera_index}"
            )

        self.cap.set(
            cv2.CAP_PROP_FRAME_WIDTH,
            self.frame_width
        )
        self.cap.set(
            cv2.CAP_PROP_FRAME_HEIGHT,
            self.frame_height
        )
        self.cap.set(
            cv2.CAP_PROP_FPS,
            self.fps
        )

        actual_w = int(
            self.cap.get(cv2.CAP_PROP_FRAME_WIDTH)
        )
        actual_h = int(
            self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT)
        )
        actual_fps = self.cap.get(cv2.CAP_PROP_FPS)

        self.get_logger().info(
            f"Camera opened | "
            f"actual resolution={actual_w}x{actual_h} "
            f"actual_fps={actual_fps:.1f}"
        )

    # =============================================================
    # PUBLISH FRAME
    # =============================================================

    def publish_frame(self):

        if self.cap is None or not self.cap.isOpened():
            self.get_logger().warning(
                "Camera not available, attempting reconnect..."
            )
            try:
                self._open_camera()
            except RuntimeError:
                return
            return

        ret, frame = self.cap.read()

        if not ret:
            self.get_logger().warning("Frame not received")
            return

        # Convert to ROS Image and publish
        msg = self.bridge.cv2_to_imgmsg(frame, encoding="bgr8")
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.header.frame_id = "camera"

        self.publisher.publish(msg)

        # ---------------------------------------------------------
        # Periodic FPS logging
        # ---------------------------------------------------------

        self.frame_count += 1
        elapsed = time.time() - self.fps_start_time

        if elapsed >= self.fps_log_interval:
            measured_fps = self.frame_count / elapsed

            self.get_logger().info(
                f"Camera FPS: {measured_fps:.1f}"
            )

            self.frame_count = 0
            self.fps_start_time = time.time()

    # =============================================================
    # CLEANUP
    # =============================================================

    def destroy_node(self):
        if self.cap is not None:
            self.cap.release()
        super().destroy_node()


# =================================================================
# MAIN
# =================================================================

def main(args=None):

    rclpy.init(args=args)

    node = CameraNode()

    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()