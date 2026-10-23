#!/usr/bin/env python3

import os
import subprocess
import sys
import threading
import time

import cv2
import numpy as np
import rclpy
from cv_bridge import CvBridge
from rclpy.node import Node
from rclpy.qos import QoSProfile, QoSDurabilityPolicy, QoSReliabilityPolicy, QoSHistoryPolicy
from sensor_msgs.msg import CompressedImage, Image


class CameraNode(Node):

    def __init__(self):
        super().__init__("camera_node")

        # ---------------------------------------------------------
        # ROS 2 parameters
        # ---------------------------------------------------------

        self.declare_parameter("camera_index", 0)
        self.declare_parameter("frame_width", 640)
        self.declare_parameter("frame_height", 480)
        self.declare_parameter("publish_width", 320)
        self.declare_parameter("publish_height", 240)
        self.declare_parameter("fps", 30)

        self.camera_index = self.get_parameter("camera_index").value
        self.frame_width = self.get_parameter("frame_width").value
        self.frame_height = self.get_parameter("frame_height").value
        self.publish_width = self.get_parameter("publish_width").value
        self.publish_height = self.get_parameter("publish_height").value
        self.fps = self.get_parameter("fps").value
        self.frame_size = self.frame_width * self.frame_height * 10 // 8

        # ---------------------------------------------------------
        # Publisher
        # ---------------------------------------------------------

        self.publisher_qos = QoSProfile(
            history=QoSHistoryPolicy.KEEP_LAST,
            depth=1,
            reliability=QoSReliabilityPolicy.RELIABLE,
            durability=QoSDurabilityPolicy.VOLATILE,
        )

        self.publisher = self.create_publisher(
            Image,
            "/camera/image_raw",
            self.publisher_qos,
        )

        self.compressed_publisher = self.create_publisher(
            CompressedImage,
            "/camera/image_compressed",
            self.publisher_qos,
        )

        self.bridge = CvBridge()

        # ---------------------------------------------------------
        # Capture state
        # ---------------------------------------------------------

        self.media_device = self._detect_ov5647_media_device()
        self.video_device = "/dev/video0"
        self.sensor_device = "/dev/v4l-subdev2"

        if not os.path.exists(self.video_device):
            self.video_device = f"/dev/video{self.camera_index}"

        self.capture_process = None
        self.capture_thread = None
        self.latest_frame = None
        self.latest_frame_lock = threading.Lock()
        self.stop_event = threading.Event()

        self.get_logger().info(
            f"Detected OV5647 media device: {self.media_device} | "
            f"video_device={self.video_device} | "
            f"sensor_device={self.sensor_device}"
        )

        self._stop_competing_camera_processes()
        self._setup_camera_media_graph()
        self._apply_ov5647_controls()
        self._start_capture_thread()

        # ---------------------------------------------------------
        # Timer
        # ---------------------------------------------------------

        timer_period = 1.0 / self.fps
        self.timer = self.create_timer(timer_period, self.publish_frame)

        # ---------------------------------------------------------
        # FPS tracking
        # ---------------------------------------------------------

        self.frame_count = 0
        self.fps_start_time = time.time()
        self.fps_log_interval = 5.0  # seconds

        self.get_logger().info(
            f"Camera Node started | "
            f"index={self.camera_index} "
            f"Capture resolution: {self.frame_width}x{self.frame_height} | "
            f"Publish resolution: {self.publish_width}x{self.publish_height} | "
            f"target_fps={self.fps}"
        )

    def _run_command(self, cmd):
        """Run a shell command and raise a useful error if it fails."""
        self.get_logger().info(f"Running command: {' '.join(cmd)}")
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            shell=False,
            check=False,
        )

        if result.stdout:
            self.get_logger().info(result.stdout.strip())
        if result.stderr:
            self.get_logger().error(result.stderr.strip())

        self.get_logger().info(f"Return code: {result.returncode}")

        if result.returncode != 0:
            raise RuntimeError(
                f"Camera command failed: cmd={cmd} | "
                f"returncode={result.returncode} | "
                f"stdout={result.stdout.strip() or '<empty>'} | "
                f"stderr={result.stderr.strip() or '<empty>'}"
            )

    def _run_media_ctl(self, *args):
        """Run media-ctl with a normal and sudo fallback."""
        cmd_candidates = [
            ["media-ctl", "-d", self.media_device, *args],
            ["sudo", "-n", "media-ctl", "-d", self.media_device, *args],
        ]

        last_error = None
        for cmd in cmd_candidates:
            try:
                result = subprocess.run(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    shell=False,
                    check=False,
                )
            except FileNotFoundError as exc:
                last_error = str(exc)
                continue

            if result.returncode == 0:
                if result.stdout:
                    self.get_logger().info(result.stdout.strip())
                if result.stderr:
                    self.get_logger().warning(result.stderr.strip())
                return

            last_error = result.stderr.strip() or result.stdout.strip() or "unknown media-ctl failure"

        raise RuntimeError(f"media-ctl failed: {last_error}")

    def _detect_ov5647_media_device(self):
        """Scan media devices and select the one that matches the OV5647 CSI2 topology."""
        candidates = [
            "/dev/media0",
            "/dev/media1",
            "/dev/media2",
            "/dev/media3",
        ]
        checked = []

        for device in candidates:
            checked.append(device)
            if not os.path.exists(device):
                continue

            try:
                result = subprocess.run(
                    ["media-ctl", "-d", device, "-p"],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    shell=False,
                    check=False,
                )
            except FileNotFoundError:
                continue

            output = (result.stdout or "") + (result.stderr or "")
            lower = output.lower()
            if "ov5647 10-0036" in lower and "rp1-cfe-csi2_ch0" in lower:
                self.get_logger().info(f"Detected OV5647 media device: {device}")
                return device

        raise RuntimeError(
            "Could not detect OV5647 media device. Checked: "
            + ", ".join(checked)
        )

    def _stop_competing_camera_processes(self):
        """Stop stale raw capture processes that can hold the CSI stream and block media graph setup."""
        self.get_logger().info("Checking for competing camera capture processes")
        try:
            subprocess.run(
                ["bash", "-lc", "pkill -f 'v4l2-ctl .*--stream-mmap' || true; pkill -f 'python.*ov5647.*camera' || true"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
            )
        except Exception as exc:
            self.get_logger().warning(f"Unable to stop competing camera processes: {exc}")

    def _setup_camera_media_graph(self):
        """Apply the working RP1-CFE media routing used by the standalone capture script."""
        self.get_logger().info("Resetting media graph and configuring OV5647 CSI2 routing")
        try:
            self._run_media_ctl("-r")
        except RuntimeError as exc:
            self.get_logger().warning(f"Media graph reset reported a busy resource; continuing with existing config: {exc}")

        for cmd in [
            ["-l", '"csi2":4 -> "rp1-cfe-csi2_ch0":0 [1]'],
            ["-l", '"csi2":4 -> "pisp-fe":0 [0]'],
            ["-V", '"ov5647 10-0036":0 [fmt:SGBRG10_1X10/640x480 field:none colorspace:raw]'],
            ["-V", '"csi2":0 [fmt:SGBRG10_1X10/640x480 field:none colorspace:raw]'],
            ["-V", '"csi2":4 [fmt:SGBRG10_1X10/640x480 field:none colorspace:raw]'],
        ]:
            try:
                self._run_media_ctl(*cmd)
            except RuntimeError as exc:
                self.get_logger().warning(f"media-ctl setup step failed but continuing: {cmd} -> {exc}")

        self._run_command([
            "v4l2-ctl",
            "-d",
            self.video_device,
            "--set-fmt-video=width=640,height=480,pixelformat=pGAA,field=none",
        ])

    def _apply_ov5647_controls(self):
        """Apply the OV5647 exposure/gain settings only when supported by the sensor."""
        sensor = self.sensor_device
        if not os.path.exists(sensor):
            self.get_logger().warning(
                f"OV5647 sensor device {sensor} is not present; skipping control configuration."
            )
            return

        try:
            self._run_command([
                "v4l2-ctl",
                "-d",
                sensor,
                "--set-ctrl=white_balance_automatic=1",
            ])
            self._run_command([
                "v4l2-ctl",
                "-d",
                sensor,
                "--set-ctrl=test_pattern=0",
            ])
            self._run_command([
                "v4l2-ctl",
                "-d",
                sensor,
                "--set-ctrl=auto_exposure=1,exposure=500,analogue_gain=1023",
            ])

            readback = subprocess.run(
                ["v4l2-ctl", "-d", sensor, "--get-ctrl=auto_exposure,exposure,analogue_gain"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                shell=False,
                check=False,
            )

            if readback.stdout:
                self.get_logger().info(f"OV5647 controls readback: {readback.stdout.strip()}")
            if readback.stderr:
                self.get_logger().warning(f"OV5647 controls readback warning: {readback.stderr.strip()}")

        except RuntimeError as exc:
            self.get_logger().error(f"OV5647 control configuration failed for {sensor}: {exc}")
            try:
                list_result = subprocess.run(
                    ["v4l2-ctl", "-d", sensor, "--list-ctrls"],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    shell=False,
                    check=False,
                )
                if list_result.stdout:
                    self.get_logger().error(f"OV5647 supported controls: {list_result.stdout.strip()}")
                if list_result.stderr:
                    self.get_logger().error(f"OV5647 control query stderr: {list_result.stderr.strip()}")
            except Exception as list_exc:
                self.get_logger().error(f"Unable to query OV5647 supported controls for {sensor}: {list_exc}")
            raise

    @staticmethod
    def unpack_raw10(raw):
        """Convert packed RAW10 bytes to 10-bit Bayer values."""
        if len(raw) != 640 * 480 * 10 // 8:
            raise ValueError(f"Invalid frame size: {len(raw)}")

        a = np.frombuffer(raw, dtype=np.uint8).reshape(-1, 5)
        p0 = (a[:, 0].astype(np.uint16) << 2) | ((a[:, 4] >> 0) & 0x03)
        p1 = (a[:, 1].astype(np.uint16) << 2) | ((a[:, 4] >> 2) & 0x03)
        p2 = (a[:, 2].astype(np.uint16) << 2) | ((a[:, 4].astype(np.uint16) >> 4) & 0x03)
        p3 = (a[:, 3].astype(np.uint16) << 2) | ((a[:, 4].astype(np.uint16) >> 6) & 0x03)
        pixels = np.column_stack((p0, p1, p2, p3))
        return pixels.reshape(480, 640)

    @staticmethod
    def read_exact(stream, size):
        """Read exactly size bytes from a subprocess stream or return what is available."""
        chunks = []
        remaining = size
        while remaining > 0:
            chunk = stream.read(remaining)
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        if not chunks:
            return b""
        return b"".join(chunks)

    def _start_capture_subprocess(self):
        """Start the working v4l2-ctl raw capture subprocess."""
        if self.capture_process is not None and self.capture_process.poll() is None:
            return

        self.get_logger().warning(
            "Stop any standalone camera process before launching the ROS camera node; "
            "competing raw captures can lock the media graph."
        )

        cmd = [
            "v4l2-ctl",
            "-d",
            self.video_device,
            "--stream-mmap=4",
            "--stream-to=-",
        ]

        self.capture_process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0,
        )

    def _capture_worker(self):
        """Continuously read RAW10 bytes from the V4L2 stream and update the latest frame."""
        while not self.stop_event.is_set():
            if self.capture_process is None or self.capture_process.poll() is not None:
                try:
                    self._start_capture_subprocess()
                except Exception as exc:
                    self.get_logger().warning(f"Capture subprocess start failed: {exc}")
                    time.sleep(0.2)
                    continue

            try:
                raw = self.read_exact(self.capture_process.stdout, self.frame_size)
            except Exception as exc:
                self.get_logger().warning(f"Capture read failed: {exc}")
                time.sleep(0.2)
                continue

            if len(raw) == 0:
                try:
                    if self.capture_process.stderr is not None:
                        error_chunk = self.capture_process.stderr.read().decode(errors="replace")
                        if error_chunk:
                            self.get_logger().warning(f"Capture subprocess stderr: {error_chunk.strip()}")
                except Exception:
                    pass
                self.get_logger().warning("Camera stream ended; restarting capture process")
                self.capture_process = None
                time.sleep(0.2)
                continue

            if len(raw) != self.frame_size:
                self.get_logger().warning(
                    f"Short frame received: {len(raw)} bytes (expected {self.frame_size})"
                )
                self.capture_process = None
                time.sleep(0.2)
                continue

            try:
                bayer10 = self.unpack_raw10(raw)
                bayer8 = (bayer10 >> 2).astype(np.uint8)
                frame = cv2.cvtColor(bayer8, cv2.COLOR_BayerGB2BGR)
                with self.latest_frame_lock:
                    self.latest_frame = frame.copy()
            except Exception as exc:
                self.get_logger().error(f"RAW10 decode failed: {exc}")
                self.capture_process = None
                time.sleep(0.2)
                continue

    def _start_capture_thread(self):
        """Start a dedicated capture thread so the ROS executor is never blocked while reading camera bytes."""
        self.stop_event.clear()
        self._start_capture_subprocess()
        self.capture_thread = threading.Thread(target=self._capture_worker, daemon=True)
        self.capture_thread.start()

    def publish_frame(self):
        """Publish the latest BGR frame from the dedicated capture thread."""
        with self.latest_frame_lock:
            frame = None if self.latest_frame is None else self.latest_frame.copy()

        if frame is None:
            return

        published_frame = cv2.resize(
            frame,
            (self.publish_width, self.publish_height),
            interpolation=cv2.INTER_AREA,
        )

        msg = self.bridge.cv2_to_imgmsg(published_frame, encoding="bgr8")
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.header.frame_id = "camera"
        self.publisher.publish(msg)

        success, encoded = cv2.imencode(".jpg", published_frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
        if success:
            compressed_msg = CompressedImage()
            compressed_msg.header.stamp = msg.header.stamp
            compressed_msg.header.frame_id = msg.header.frame_id
            compressed_msg.format = "jpeg"
            compressed_msg.data = encoded.tobytes()
            self.compressed_publisher.publish(compressed_msg)

        self.frame_count += 1
        elapsed = time.time() - self.fps_start_time

        if elapsed >= self.fps_log_interval:
            measured_fps = self.frame_count / elapsed
            self.get_logger().info(f"Camera FPS: {measured_fps:.1f}")
            self.frame_count = 0
            self.fps_start_time = time.time()

    def destroy_node(self):
        self.stop_event.set()

        if self.capture_process is not None:
            try:
                self.capture_process.terminate()
                self.capture_process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.capture_process.kill()
            except Exception:
                pass
            self.capture_process = None

        if self.capture_thread is not None and self.capture_thread.is_alive():
            self.capture_thread.join(timeout=2)

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