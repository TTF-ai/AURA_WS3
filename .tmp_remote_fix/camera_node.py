#!/usr/bin/env python3

import glob
import os
import re
import subprocess
import time

import cv2
import numpy as np
import rclpy
from cv_bridge import CvBridge
from rclpy.node import Node
from rclpy.qos import (
    QoSDurabilityPolicy,
    QoSHistoryPolicy,
    QoSProfile,
    QoSReliabilityPolicy,
)
from sensor_msgs.msg import CompressedImage, Image


class CameraNode(Node):
    def __init__(self):
        super().__init__("camera_node")

        self.declare_parameter("camera_index", 0)
        self.declare_parameter("frame_width", 640)
        self.declare_parameter("frame_height", 480)
        self.declare_parameter("publish_width", 320)
        self.declare_parameter("publish_height", 240)
        self.declare_parameter("jpeg_quality", 70)
        self.declare_parameter("fps", 30)
        self.declare_parameter("video_device", "")
        self.declare_parameter("media_device", "")
        self.declare_parameter("sensor_device", "")

        self.camera_index = self.get_parameter("camera_index").value
        self.frame_width = self.get_parameter("frame_width").value
        self.frame_height = self.get_parameter("frame_height").value
        self.publish_width = self.get_parameter("publish_width").value
        self.publish_height = self.get_parameter("publish_height").value
        self.jpeg_quality = self.get_parameter("jpeg_quality").value
        self.fps = self.get_parameter("fps").value
        self.video_device = self.get_parameter("video_device").value or ""
        self.media_device = self.get_parameter("media_device").value or ""
        self.sensor_device = self.get_parameter("sensor_device").value or ""

        self.frame_size = self.frame_width * self.frame_height * 10 // 8
        self.max_retries = 4
        self.retry_delay = 0.75
        self.capture_process = None
        self.ready = False

        self.publisher_qos = QoSProfile(
            history=QoSHistoryPolicy.KEEP_LAST,
            depth=1,
            reliability=QoSReliabilityPolicy.BEST_EFFORT,
            durability=QoSDurabilityPolicy.VOLATILE,
        )

        self.publisher = self.create_publisher(Image, "/camera/image_raw", self.publisher_qos)
        self.compressed_publisher = self.create_publisher(
            CompressedImage,
            "/camera/image_compressed",
            self.publisher_qos,
        )

        self.bridge = CvBridge()
        self.frame_count = 0
        self.fps_start_time = time.time()
        self.fps_log_interval = 5.0

        self._open_camera()

        timer_period = 1.0 / self.fps
        self.timer = self.create_timer(timer_period, self.publish_frame)

        self.get_logger().info(
            "Camera Node started | "
            f"index={self.camera_index} "
            f"video={self.video_device} "
            f"media={self.media_device} "
            f"sensor={self.sensor_device} "
            f"resolution={self.frame_width}x{self.frame_height} | "
            f"publish={self.publish_width}x{self.publish_height} | "
            f"target_fps={self.fps}"
        )

    def _detect_camera_candidates(self):
        candidates = []
        seen = set()

        configured = {
            "video_device": self.video_device,
            "media_device": self.media_device,
            "sensor_device": self.sensor_device,
        }
        if all(configured.values()):
            candidates.append(configured)

        for media_path in sorted(glob.glob("/dev/media*")):
            try:
                result = subprocess.run(
                    ["media-ctl", "-p", "-d", media_path],
                    capture_output=True,
                    text=True,
                    timeout=2,
                    check=False,
                )
            except (FileNotFoundError, subprocess.SubprocessError):
                continue

            if result.returncode != 0:
                continue

            topology = result.stdout or ""
            if "ov5647" not in topology.lower():
                continue

            video_paths = re.findall(r"/dev/video\d+", topology)
            sensor_paths = re.findall(r"/dev/v4l-subdev\d+", topology)
            if not video_paths or not sensor_paths:
                continue

            candidate = {
                "media_device": media_path,
                "video_device": video_paths[0],
                "sensor_device": sensor_paths[0],
            }
            key = (
                candidate["media_device"],
                candidate["video_device"],
                candidate["sensor_device"],
            )
            if key not in seen:
                seen.add(key)
                candidates.append(candidate)

        if not candidates:
            for media_path in ["/dev/media0", "/dev/media1", "/dev/media2", "/dev/media3"]:
                if not os.path.exists(media_path):
                    continue
                for video_path in [
                    "/dev/video0",
                    "/dev/video1",
                    "/dev/video2",
                    "/dev/video3",
                    "/dev/video4",
                    "/dev/video5",
                    "/dev/video6",
                    "/dev/video7",
                ]:
                    if not os.path.exists(video_path):
                        continue
                    for sensor_path in [
                        "/dev/v4l-subdev0",
                        "/dev/v4l-subdev1",
                        "/dev/v4l-subdev2",
                    ]:
                        if not os.path.exists(sensor_path):
                            continue
                        candidate = {
                            "media_device": media_path,
                            "video_device": video_path,
                            "sensor_device": sensor_path,
                        }
                        key = (
                            candidate["media_device"],
                            candidate["video_device"],
                            candidate["sensor_device"],
                        )
                        if key not in seen:
                            seen.add(key)
                            candidates.append(candidate)

        return candidates

    def _run_command(self, cmd):
        command_string = " ".join(cmd)
        self.get_logger().info(f"Running camera command: {command_string}")

        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            shell=False,
            check=False,
        )

        if result.stdout:
            self.get_logger().info("Command stdout:\n" + str(result.stdout))
        if result.stderr:
            self.get_logger().error("Command stderr:\n" + str(result.stderr))

        self.get_logger().info(f"Command return code: {result.returncode}")
        if result.returncode != 0:
            raise RuntimeError(
                f"Camera command failed: "
                f"cmd={command_string} | "
                f"returncode={result.returncode} | "
                f"stdout={result.stdout.strip() or '<empty>'} | "
                f"stderr={result.stderr.strip() or '<empty>'}"
            )

        return result.stdout.strip()

    def _close_camera(self):
        if self.capture_process is not None:
            self.capture_process.terminate()
            try:
                self.capture_process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.capture_process.kill()
                self.capture_process.wait(timeout=2)
            self.capture_process = None

    def _configure_media_pipeline(self):
        self._run_command(["media-ctl", "-d", self.media_device, "-r"])
        self._run_command(["media-ctl", "-d", self.media_device, "-l", '"csi2":4 -> "rp1-cfe-csi2_ch0":0 [1]'])
        self._run_command(["media-ctl", "-d", self.media_device, "-l", '"csi2":4 -> "pisp-fe":0 [0]'])

        raw_format = (
            f"fmt:SGBRG10_1X10/{self.frame_width}x{self.frame_height} "
            "field:none colorspace:raw"
        )

        self._run_command(["media-ctl", "-d", self.media_device, "-V", f'"ov5647 10-0036":0 [{raw_format}]'])
        self._run_command(["media-ctl", "-d", self.media_device, "-V", f'"csi2":0 [{raw_format}]'])
        self._run_command(["media-ctl", "-d", self.media_device, "-V", f'"csi2":4 [{raw_format}]'])

        self._run_command(
            [
                "v4l2-ctl",
                "-d",
                self.video_device,
                f"--set-fmt-video=width={self.frame_width},height={self.frame_height},pixelformat=pGAA,field=none",
            ]
        )

    def _start_capture(self):
        self.capture_process = subprocess.Popen(
            [
                "v4l2-ctl",
                "-d",
                self.video_device,
                "--stream-mmap=4",
                "--stream-to=-",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0,
        )

        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            if self.capture_process.poll() is not None:
                raise RuntimeError(f"Camera capture process exited early on {self.video_device}")
            if self.capture_process.stdout is None:
                time.sleep(0.05)
                continue
            try:
                chunk = self.capture_process.stdout.read(1)
            except Exception:
                chunk = b""
            if chunk:
                self.get_logger().info(
                    "Camera validation passed | "
                    f"device={self.video_device} | bytes_read={len(chunk)}"
                )
                return
            time.sleep(0.05)

        raise RuntimeError(f"No valid frame received from {self.video_device}")

    def _open_camera(self):
        self._close_camera()
        candidates = self._detect_camera_candidates()
        if not candidates:
            raise RuntimeError(
                "No Raspberry Pi CSI camera media topology detected. "
                "Tried /dev/media* and /dev/video* but no OV5647 sensor was found."
            )

        last_error = None
        for attempt in range(1, self.max_retries + 1):
            for candidate in candidates:
                self.media_device = candidate["media_device"]
                self.video_device = candidate["video_device"]
                self.sensor_device = candidate["sensor_device"]

                self.get_logger().info(
                    f"Camera attempt {attempt}/{self.max_retries} | media={self.media_device} | video={self.video_device} | sensor={self.sensor_device}"
                )

                try:
                    self._configure_media_pipeline()
                    self._start_capture()
                    self.ready = True
                    self.get_logger().info(
                        "Camera ready | "
                        f"media={self.media_device} | video={self.video_device} | sensor={self.sensor_device}"
                    )
                    return
                except Exception as exc:
                    last_error = exc
                    self.get_logger().warning(
                        "Camera attempt failed | "
                        f"media={self.media_device} | video={self.video_device} | sensor={self.sensor_device} | error={exc}"
                    )
                    self._close_camera()
                    time.sleep(self.retry_delay * attempt)

        raise RuntimeError(f"No valid camera found after retries. Last error: {last_error}")

    def _read_exact(self, size):
        if self.capture_process is None or self.capture_process.stdout is None:
            return b""

        chunks = []
        remaining = size
        while remaining > 0:
            chunk = self.capture_process.stdout.read(min(65536, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        return b"".join(chunks)

    def _decode_frame(self, raw):
        packed = np.frombuffer(raw, dtype=np.uint8).reshape(-1, 5)

        p0 = (packed[:, 0].astype(np.uint16) << 2) | (packed[:, 4] & 0x03)
        p1 = (packed[:, 1].astype(np.uint16) << 2) | ((packed[:, 4] >> 2) & 0x03)
        p2 = (packed[:, 2].astype(np.uint16) << 2) | ((packed[:, 4] >> 4) & 0x03)
        p3 = (packed[:, 3].astype(np.uint16) << 2) | ((packed[:, 4] >> 6) & 0x03)

        bayer10 = np.column_stack((p0, p1, p2, p3)).reshape(self.frame_height, self.frame_width)
        bayer8 = (bayer10 >> 2).astype(np.uint8)
        return cv2.cvtColor(bayer8, cv2.COLOR_BayerGB2BGR)

    def publish_frame(self):
        if not self.ready:
            return

        if self.capture_process is None or self.capture_process.poll() is not None:
            self.get_logger().warning("Camera not available, attempting reconnect...")
            try:
                self._open_camera()
            except RuntimeError as error:
                self.get_logger().error(f"Camera reconnect failed: {error}")
                return
            return

        raw = self._read_exact(self.frame_size)
        if len(raw) != self.frame_size:
            self.get_logger().warning("Frame not received from camera stream; retrying")
            return

        frame = self._decode_frame(raw)
        published_frame = cv2.resize(
            frame,
            (self.publish_width, self.publish_height),
            interpolation=cv2.INTER_AREA,
        )

        success, encoded = cv2.imencode(
            ".jpg",
            published_frame,
            [cv2.IMWRITE_JPEG_QUALITY, self.jpeg_quality],
        )
        if success:
            compressed_msg = CompressedImage()
            compressed_msg.header.stamp = self.get_clock().now().to_msg()
            compressed_msg.header.frame_id = "camera"
            compressed_msg.format = "jpeg"
            compressed_msg.data = encoded.tobytes()
            self.compressed_publisher.publish(compressed_msg)

        msg = self.bridge.cv2_to_imgmsg(published_frame, encoding="bgr8")
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.header.frame_id = "camera"
        self.publisher.publish(msg)

        self.frame_count += 1
        elapsed = time.time() - self.fps_start_time
        if elapsed >= self.fps_log_interval:
            measured_fps = self.frame_count / elapsed
            self.get_logger().info(f"Camera FPS: {measured_fps:.1f}")
            self.frame_count = 0
            self.fps_start_time = time.time()

    def destroy_node(self):
        self._close_camera()
        super().destroy_node()


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
