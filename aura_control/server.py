#!/usr/bin/env python3
import json
import os
import shutil
import subprocess
import threading
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

try:
    import rclpy
    from cv_bridge import CvBridge
    from rclpy.node import Node
    from sensor_msgs.msg import Image
except Exception:  # pragma: no cover - ROS not available in the current runtime
    rclpy = None
    CvBridge = None
    Node = None
    Image = None

ROOT_DIR = Path(__file__).resolve().parent
WORKSPACE_DIR = ROOT_DIR.parent
HOST = "0.0.0.0"
PORT = 8000

FEATURE_PATHS = {
    "voice": ROOT_DIR.parent / "src" / "aura_voice" / "launch" / "voice.launch.py",
    "slam": ROOT_DIR.parent / "src" / "aura_bringup" / "launch" / "slam.launch.py",
    "semantic_map": ROOT_DIR.parent / "src" / "aura_sem_map" / "launch" / "semantic_map.launch.py",
    "navigation": ROOT_DIR.parent / "src" / "aura_navigation" / "config" / "nav2_params.yaml",
    "human_follow": ROOT_DIR.parent / "src" / "aura_follow" / "launch" / "human_follow.launch.py",
    "face_auth": ROOT_DIR.parent / "src" / "aura_face_auth" / "launch" / "face_auth.launch.py",
    "behavior": ROOT_DIR.parent / "src" / "aura_behavior" / "launch" / "behavior.launch.py",
    "alert": ROOT_DIR.parent / "src" / "aura_alert" / "launch" / "alert.launch.py",
    "exploration": ROOT_DIR.parent / "src" / "aura_exploration" / "launch" / "exploration.launch.py",
    "robot_stack": ROOT_DIR.parent / "src" / "aura_bringup" / "launch" / "robot.launch.py",
}


class CameraFrameBridge(Node if Node is not None else object):
    def __init__(self):
        if Node is None:
            raise RuntimeError("ROS dependencies are not available in this environment.")
        super().__init__('aura_dashboard_camera_bridge')
        self.bridge = CvBridge()
        self.latest_frame = None
        self.latest_frame_lock = threading.Lock()
        self.subscription = self.create_subscription(
            Image,
            '/camera/image',
            self._camera_callback,
            1,
        )
        self.subscription  # keep reference

    def _camera_callback(self, msg):
        try:
            cv_image = self.bridge.imgmsg_to_cv2(msg, desired_encoding='bgr8')
            _, jpg = cv2.imencode('.jpg', cv_image, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
            if jpg is not None:
                with self.latest_frame_lock:
                    self.latest_frame = jpg.tobytes()
        except Exception:
            self.latest_frame = None

    def get_latest_frame(self):
        with self.latest_frame_lock:
            return self.latest_frame


ROS_CAMERA_BRIDGE = None
ROS_SPIN_THREAD = None


def ensure_ros_camera_bridge():
    global ROS_CAMERA_BRIDGE, ROS_SPIN_THREAD
    if rclpy is None or Node is None or Image is None:
        return None
    if ROS_CAMERA_BRIDGE is not None:
        return ROS_CAMERA_BRIDGE

    try:
        import cv2
        global cv2
        rclpy.init(args=None)
        ROS_CAMERA_BRIDGE = CameraFrameBridge()

        def spin_bridge():
            rclpy.spin(ROS_CAMERA_BRIDGE)

        ROS_SPIN_THREAD = threading.Thread(target=spin_bridge, daemon=True)
        ROS_SPIN_THREAD.start()
        return ROS_CAMERA_BRIDGE
    except Exception:
        return None


def run_command(cmd):
    try:
        proc = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
        return {
            "ok": proc.returncode == 0,
            "stdout": proc.stdout.strip(),
            "stderr": proc.stderr.strip(),
            "returncode": proc.returncode,
        }
    except Exception as exc:  # pragma: no cover - safe guard
        return {"ok": False, "stdout": "", "stderr": str(exc), "returncode": 1}


def terminal_status_for(label, session_name, remote_host=None):
    if remote_host:
        command = (
            f"ssh -o BatchMode=yes -o ConnectTimeout=5 {remote_host} "
            f"'tmux has-session -t {session_name} 2>/dev/null && echo ACTIVE || echo MISSING'"
        )
    else:
        command = f"tmux has-session -t {session_name} 2>/dev/null && echo ACTIVE || echo MISSING"

    result = run_command(command)
    status = "ACTIVE" if result["ok"] and "ACTIVE" in result["stdout"] else "MISSING"
    is_active = status == "ACTIVE"
    return {
        "label": label,
        "session": session_name,
        "host": remote_host or "localhost",
        "active": is_active,
        "status": status,
        "details": result,
    }


def workspace_status():
    feature_state = {}
    for name, path in FEATURE_PATHS.items():
        feature_state[name] = path.exists()

    return {
        "features": feature_state,
        "terminals": [
            terminal_status_for("Laptop", "aura_laptop"),
            terminal_status_for("RPI 5", "aura_rpi", "robo@10.123.81.187"),
        ],
        "workspace": str(WORKSPACE_DIR),
    }


class AuraHandler(SimpleHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        def write_response_bytes(data):
            try:
                self.wfile.write(data)
            except BrokenPipeError:
                pass

        if path == "/api/system-status":
            payload = json.dumps(workspace_status()).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            write_response_bytes(payload)
            return

        if path == "/api/camera/frame":
            bridge = ensure_ros_camera_bridge()
            frame = bridge.get_latest_frame() if bridge is not None else None
            if frame is None:
                payload = json.dumps({"error": "No camera frame available yet."}).encode("utf-8")
                self.send_response(503)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                write_response_bytes(payload)
                return

            self.send_response(200)
            self.send_header("Content-Type", "image/jpeg")
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
            self.send_header("Content-Length", str(len(frame)))
            self.end_headers()
            write_response_bytes(frame)
            return

        if path == "/api/camera/stream":
            bridge = ensure_ros_camera_bridge()
            if bridge is None:
                payload = json.dumps({"error": "ROS camera stream is not available."}).encode("utf-8")
                self.send_response(503)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                write_response_bytes(payload)
                return

            self.send_response(200)
            self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=AURA_STREAM")
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate, max-age=0")
            self.send_header("Pragma", "no-cache")
            self.send_header("Connection", "close")
            self.end_headers()

            boundary = b"--AURA_STREAM\r\n"
            try:
                while True:
                    frame = bridge.get_latest_frame()
                    if frame is not None:
                        self.wfile.write(boundary)
                        self.wfile.write(b"Content-Type: image/jpeg\r\n")
                        self.wfile.write(f"Content-Length: {len(frame)}\r\n\r\n".encode("utf-8"))
                        self.wfile.write(frame)
                        self.wfile.write(b"\r\n")
                        self.wfile.flush()
                    time.sleep(0.1)
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass
            return

        if path == "/":
            index_path = ROOT_DIR / "index.html"
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(index_path.stat().st_size))
            self.end_headers()
            with index_path.open("rb") as handle:
                try:
                    self.wfile.write(handle.read())
                except BrokenPipeError:
                    pass
            return

        if path.startswith("/api/"):
            self.send_response(404)
            self.end_headers()
            return

        if path.startswith("/"):
            safe = (ROOT_DIR / path.lstrip("/")).resolve()
            try:
                safe.relative_to(ROOT_DIR)
            except ValueError:
                self.send_response(404)
                self.end_headers()
                return

            if safe.is_file():
                mime_map = {
                    ".css": "text/css; charset=utf-8",
                    ".js": "application/javascript; charset=utf-8",
                    ".html": "text/html; charset=utf-8",
                    ".json": "application/json; charset=utf-8",
                    ".svg": "image/svg+xml",
                    ".png": "image/png",
                    ".jpg": "image/jpeg",
                    ".jpeg": "image/jpeg",
                    ".ico": "image/x-icon",
                }
                content_type = mime_map.get(safe.suffix.lower(), "application/octet-stream")
                file_bytes = safe.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(file_bytes)))
                self.end_headers()
                self.wfile.write(file_bytes)
                return

            self.send_response(404)
            self.end_headers()
            return

    def log_message(self, format, *args):
        return


def main():
    handler = AuraHandler
    httpd = ThreadingHTTPServer((HOST, PORT), handler)
    print(f"AURA control dashboard running on http://{HOST}:{PORT}")
    httpd.serve_forever()


if __name__ == "__main__":
    main()
