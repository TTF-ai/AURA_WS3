#!/usr/bin/env python3

import rclpy
from rclpy.node import Node

import cv2
import numpy as np

from sensor_msgs.msg import CompressedImage, Image
from cv_bridge import CvBridge

from rclpy.qos import (
    QoSProfile,
    ReliabilityPolicy,
    HistoryPolicy,
    DurabilityPolicy
)


class JPEGDecoderNode(Node):

    def __init__(self):
        super().__init__("jpeg_decoder_node")

        self.bridge = CvBridge()

        # ==========================================================
        # INPUT QoS
        # Matches RPi5 camera_node
        # /camera/image_compressed
        # ==========================================================
        input_qos = QoSProfile(
            history=HistoryPolicy.KEEP_LAST,
            depth=1,
            reliability=ReliabilityPolicy.BEST_EFFORT,
            durability=DurabilityPolicy.VOLATILE
        )

        # ==========================================================
        # OUTPUT QoS
        # Used by RViz and local AI nodes
        # /camera/image
        # ==========================================================
        output_qos = QoSProfile(
            history=HistoryPolicy.KEEP_LAST,
            depth=1,
            reliability=ReliabilityPolicy.RELIABLE,
            durability=DurabilityPolicy.VOLATILE
        )

        # ==========================================================
        # SUBSCRIBER
        # ==========================================================
        self.subscription = self.create_subscription(
            CompressedImage,
            "/camera/image_compressed",
            self.image_callback,
            input_qos
        )

        # ==========================================================
        # PUBLISHER
        # ==========================================================
        self.publisher = self.create_publisher(
            Image,
            "/camera/image",
            output_qos
        )

        # FPS
        self.frame_count = 0
        self.last_log_time = self.get_clock().now()

        self.get_logger().info(
            "=========================================="
        )
        self.get_logger().info(
            "AURA JPEG Decoder Node Started"
        )
        self.get_logger().info(
            "Input  : /camera/image_compressed"
        )
        self.get_logger().info(
            "Output : /camera/image"
        )
        self.get_logger().info(
            "Input QoS  : BEST_EFFORT"
        )
        self.get_logger().info(
            "Output QoS : RELIABLE"
        )
        self.get_logger().info(
            "=========================================="
        )

    def image_callback(self, msg):

        try:

            # ------------------------------------------------------
            # JPEG bytes → NumPy array
            # ------------------------------------------------------
            np_arr = np.frombuffer(
                msg.data,
                dtype=np.uint8
            )

            # ------------------------------------------------------
            # JPEG → OpenCV BGR
            # ------------------------------------------------------
            frame = cv2.imdecode(
                np_arr,
                cv2.IMREAD_COLOR
            )

            if frame is None:
                self.get_logger().warning(
                    "Failed to decode JPEG"
                )
                return

            # ------------------------------------------------------
            # OpenCV → ROS Image
            # ------------------------------------------------------
            image_msg = self.bridge.cv2_to_imgmsg(
                frame,
                encoding="bgr8"
            )

            # Preserve camera timestamp/frame ID
            image_msg.header = msg.header

            # ------------------------------------------------------
            # Publish
            # ------------------------------------------------------
            self.publisher.publish(image_msg)

            # ------------------------------------------------------
            # FPS
            # ------------------------------------------------------
            self.frame_count += 1

            now = self.get_clock().now()

            elapsed = (
                now - self.last_log_time
            ).nanoseconds / 1e9

            if elapsed >= 5.0:

                fps = self.frame_count / elapsed

                self.get_logger().info(
                    f"Decoded FPS: {fps:.2f}"
                )

                self.frame_count = 0
                self.last_log_time = now

        except Exception as e:

            self.get_logger().error(
                f"JPEG decode error: {e}"
            )


def main(args=None):

    rclpy.init(args=args)

    node = JPEGDecoderNode()

    try:
        rclpy.spin(node)

    except KeyboardInterrupt:
        pass

    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
