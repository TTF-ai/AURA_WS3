#!/usr/bin/env python3

import glob
import json
import math
import os
import time

import rclpy
import serial
from geometry_msgs.msg import Twist
from rclpy.node import Node
from sensor_msgs.msg import Imu
from std_msgs.msg import String


class Esp32Bridge(Node):
    def __init__(self):
        super().__init__("esp32_bridge")

        self.declare_parameter("serial_port", "")
        self.declare_parameter("baud_rate", 115200)
        self.declare_parameter("connect_timeout_sec", 3.0)
        self.declare_parameter("retry_count", 5)
        self.declare_parameter("retry_backoff_sec", 0.5)

        self.serial_port = self.get_parameter("serial_port").value
        self.baud_rate = self.get_parameter("baud_rate").value
        self.connect_timeout_sec = self.get_parameter("connect_timeout_sec").value
        self.retry_count = self.get_parameter("retry_count").value
        self.retry_backoff_sec = self.get_parameter("retry_backoff_sec").value

        self.ser = None
        self.connection_state = "waiting_for_device"
        self.port = None

        self.data_pub = self.create_publisher(String, "/esp32/data", 10)
        self.imu_pub = self.create_publisher(Imu, "/esp32/imu", 10)
        self.cmd_vel_sub = self.create_subscription(Twist, "/cmd_vel", self.cmd_vel_callback, 10)

        self.connect_timer = self.create_timer(0.25, self._maintain_connection)
        self.read_timer = self.create_timer(0.01, self.read_serial)

        self._connect_serial()

    def _candidate_ports(self):
        preferred = []
        if self.serial_port:
            preferred.append(self.serial_port)

        for base in ["/dev/serial/by-id", "/dev/serial/by-path"]:
            if os.path.isdir(base):
                preferred.extend(sorted(os.path.join(base, entry) for entry in os.listdir(base)))

        preferred.extend(sorted(glob.glob("/dev/ttyUSB*")))
        preferred.extend(sorted(glob.glob("/dev/ttyACM*")))

        ports = []
        seen = set()
        for port in preferred:
            if port not in seen and os.path.exists(port):
                seen.add(port)
                ports.append(port)
        return ports

    def _close_serial(self):
        if self.ser is not None:
            try:
                if self.ser.is_open:
                    self.ser.close()
            except Exception:
                pass
            self.ser = None

    def _connect_serial(self):
        if self.ser is not None and self.ser.is_open:
            return True

        ports = self._candidate_ports()
        if not ports:
            self.get_logger().warning("ESP32 serial port not found yet; waiting for /dev/ttyUSB* or /dev/ttyACM*")
            self.connection_state = "waiting_for_device"
            return False

        self.connection_state = "connecting"
        for attempt, port in enumerate(ports, start=1):
            self.get_logger().info(f"ESP32 connect attempt {attempt}/{len(ports)} on {port}")
            self.port = port
            try:
                self.ser = serial.Serial(port, self.baud_rate, timeout=0.1, write_timeout=0.5)
                if hasattr(self.ser, "reset_input_buffer"):
                    self.ser.reset_input_buffer()
                if hasattr(self.ser, "reset_output_buffer"):
                    self.ser.reset_output_buffer()
                time.sleep(0.2)
                self.connection_state = "waiting_for_handshake"

                deadline = time.monotonic() + self.connect_timeout_sec
                while time.monotonic() < deadline:
                    if self.ser is None or not self.ser.is_open:
                        break
                    if self.ser.in_waiting > 0:
                        line = self.ser.readline().decode("utf-8", errors="replace").strip()
                        if line:
                            self.get_logger().info(f"ESP32 handshake on {port}: {line[:120]}")
                            self.connection_state = "connected"
                            return True
                    time.sleep(0.05)

                self.get_logger().warning(
                    f"ESP32 on {port} did not produce a valid handshake within {self.connect_timeout_sec}s"
                )
                self._close_serial()
            except serial.SerialException as exc:
                self.get_logger().warning(f"ESP32 serial open failed on {port}: {exc}")
                self._close_serial()
            except Exception as exc:
                self.get_logger().error(f"Unexpected ESP32 serial error on {port}: {exc}")
                self._close_serial()

        self.connection_state = "failed"
        self.get_logger().error("ESP32 bridge could not establish a valid serial connection.")
        return False

    def _maintain_connection(self):
        if self.ser is None or not self.ser.is_open:
            self.get_logger().info("ESP32 serial connection lost; attempting reconnect.")
            self.connection_state = "reconnecting"
            self._connect_serial()

    def cmd_vel_callback(self, msg):
        if self.ser is None or not self.ser.is_open:
            if not self._connect_serial():
                self.get_logger().warning("Ignoring /cmd_vel because ESP32 is not connected.")
                return

        cmd_data = {
            "cmd": "motor",
            "linear": float(msg.linear.x),
            "angular": float(msg.angular.z),
        }
        try:
            payload = (json.dumps(cmd_data) + chr(10)).encode("utf-8")
            self.ser.write(payload)
            self.ser.flush()
        except Exception as exc:
            self.get_logger().error(f"Error writing to ESP32 serial: {exc}")
            self._close_serial()

    def read_serial(self):
        if self.ser is None or not self.ser.is_open:
            return

        try:
            while self.ser.in_waiting > 0:
                line = self.ser.readline()
                if not line:
                    continue
                text = line.decode("utf-8", errors="replace").strip()
                if not text:
                    continue

                self.connection_state = "connected"
                msg = String()
                msg.data = text
                self.data_pub.publish(msg)

                try:
                    data = json.loads(text)
                    if isinstance(data, dict) and "imu" in data:
                        self.publish_imu(data["imu"])
                except json.JSONDecodeError:
                    pass
        except Exception as exc:
            self.get_logger().error(f"Error reading ESP32 serial: {exc}")
            self._close_serial()

    def publish_imu(self, imu_data):
        msg = Imu()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.header.frame_id = "imu_link"

        if "ax" in imu_data and "ay" in imu_data and "az" in imu_data:
            msg.linear_acceleration.x = float(imu_data["ax"]) * 9.80665
            msg.linear_acceleration.y = float(imu_data["ay"]) * 9.80665
            msg.linear_acceleration.z = float(imu_data["az"]) * 9.80665

        if "gx" in imu_data and "gy" in imu_data and "gz" in imu_data:
            msg.angular_velocity.x = float(imu_data["gx"]) * (math.pi / 180.0)
            msg.angular_velocity.y = float(imu_data["gy"]) * (math.pi / 180.0)
            msg.angular_velocity.z = float(imu_data["gz"]) * (math.pi / 180.0)

        msg.orientation_covariance[0] = -1.0
        self.imu_pub.publish(msg)


def main(args=None):
    rclpy.init(args=args)
    node = Esp32Bridge()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
