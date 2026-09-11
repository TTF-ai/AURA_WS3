#!/usr/bin/env python3
import rclpy
from rclpy.node import Node
import serial
import json
import math
from std_msgs.msg import String
from sensor_msgs.msg import Imu
from geometry_msgs.msg import Twist

class Esp32Bridge(Node):
    def __init__(self):
        super().__init__('esp32_bridge')
        
        self.declare_parameter('serial_port', '/dev/ttyUSB1')
        self.declare_parameter('baud_rate', 115200)
        
        port = self.get_parameter('serial_port').value
        baud = self.get_parameter('baud_rate').value
        
        try:
            self.ser = serial.Serial(port, baud, timeout=0.1)
            self.get_logger().info(f'Connected to ESP32 on {port} at {baud} baud.')
        except serial.SerialException as e:
            self.get_logger().error(f'Failed to connect to serial port: {e}')
            self.ser = None

        self.data_pub = self.create_publisher(String, '/esp32/data', 10)
        self.imu_pub = self.create_publisher(Imu, '/esp32/imu', 10)
        
        self.cmd_vel_sub = self.create_subscription(Twist, '/cmd_vel', self.cmd_vel_callback, 10)
        
        self.timer = self.create_timer(0.01, self.read_serial)

    def cmd_vel_callback(self, msg):
        if self.ser and self.ser.is_open:
            # Preserve existing motor command protocol
            # Sending JSON format expected by firmware
            cmd_data = {
                "cmd": "motor",
                "linear": msg.linear.x,
                "angular": msg.angular.z
            }
            try:
                self.ser.write((json.dumps(cmd_data) + '\n').encode('utf-8'))
            except Exception as e:
                self.get_logger().error(f'Error writing to serial: {e}')

    def read_serial(self):
        if not self.ser or not self.ser.is_open:
            return
            
        try:
            while self.ser.in_waiting > 0:
                line = self.ser.readline().decode('utf-8').strip()
                if not line:
                    continue
                    
                # Publish raw data
                msg = String()
                msg.data = line
                self.data_pub.publish(msg)
                
                # Parse for IMU
                try:
                    data = json.loads(line)
                    if 'imu' in data:
                        self.publish_imu(data['imu'])
                except json.JSONDecodeError:
                    pass
        except Exception as e:
            self.get_logger().error(f'Error reading serial: {e}')

    def publish_imu(self, imu_data):
        msg = Imu()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.header.frame_id = 'imu_link'
        
        # Acceleration: g -> m/s^2
        if 'ax' in imu_data and 'ay' in imu_data and 'az' in imu_data:
            msg.linear_acceleration.x = float(imu_data['ax']) * 9.80665
            msg.linear_acceleration.y = float(imu_data['ay']) * 9.80665
            msg.linear_acceleration.z = float(imu_data['az']) * 9.80665
            
        # Gyro: deg/s -> rad/s
        if 'gx' in imu_data and 'gy' in imu_data and 'gz' in imu_data:
            msg.angular_velocity.x = float(imu_data['gx']) * (math.pi / 180.0)
            msg.angular_velocity.y = float(imu_data['gy']) * (math.pi / 180.0)
            msg.angular_velocity.z = float(imu_data['gz']) * (math.pi / 180.0)
            
        # No orientation provided by ESP32
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

if __name__ == '__main__':
    main()
