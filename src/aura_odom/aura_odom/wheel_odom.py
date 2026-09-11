#!/usr/bin/env python3
import rclpy
from rclpy.node import Node
import json
import math
from std_msgs.msg import String
from nav_msgs.msg import Odometry
from geometry_msgs.msg import TransformStamped, Quaternion
from tf2_ros import TransformBroadcaster

class WheelOdom(Node):
    def __init__(self):
        super().__init__('wheel_odom')
        
        # ROS 2 Parameters
        self.declare_parameter('wheel_radius', 0.0425)
        self.declare_parameter('track_width', 0.327)
        self.declare_parameter('counts_per_revolution', 1280.0)
        self.declare_parameter('encoder_reset_threshold', 100000)
        
        self.wheel_radius = self.get_parameter('wheel_radius').value
        self.track_width = self.get_parameter('track_width').value
        self.counts_per_rev = self.get_parameter('counts_per_revolution').value
        self.reset_threshold = self.get_parameter('encoder_reset_threshold').value
        
        # State
        self.prev_left_counts = None
        self.prev_right_counts = None
        
        self.x = 0.0
        self.y = 0.0
        self.theta = 0.0
        
        # Pubs and Subs
        self.odom_pub = self.create_publisher(Odometry, '/odom', 10)
        self.tf_broadcaster = TransformBroadcaster(self)
        self.sub = self.create_subscription(String, '/esp32/data', self.data_callback, 10)

    def euler_to_quaternion(self, roll, pitch, yaw):
        qx = math.sin(roll/2) * math.cos(pitch/2) * math.cos(yaw/2) - math.cos(roll/2) * math.sin(pitch/2) * math.sin(yaw/2)
        qy = math.cos(roll/2) * math.sin(pitch/2) * math.cos(yaw/2) + math.sin(roll/2) * math.cos(pitch/2) * math.sin(yaw/2)
        qz = math.cos(roll/2) * math.cos(pitch/2) * math.sin(yaw/2) - math.sin(roll/2) * math.sin(pitch/2) * math.cos(yaw/2)
        qw = math.cos(roll/2) * math.cos(pitch/2) * math.cos(yaw/2) + math.sin(roll/2) * math.sin(pitch/2) * math.sin(yaw/2)
        return [qx, qy, qz, qw]

    def data_callback(self, msg):
        try:
            data = json.loads(msg.data)
            
            if 'cmd' in data and data['cmd'] == 'update' and 'encoder' in data:
                enc = data['encoder']
                
                # Extract 4 wheels
                fl = float(enc['FL']['count'])
                rl = float(enc['RL']['count'])
                fr = float(enc['FR']['count'])
                rr = float(enc['RR']['count'])
                
                # Average left and right
                left_counts = (fl + rl) / 2.0
                
                # Average right and NEGATE so forward motion = positive counts
                right_counts = -((fr + rr) / 2.0)
                
                # Initialize previous counts on first callback
                if self.prev_left_counts is None or self.prev_right_counts is None:
                    self.prev_left_counts = left_counts
                    self.prev_right_counts = right_counts
                    return
                
                # Calculate deltas
                delta_left = left_counts - self.prev_left_counts
                delta_right = right_counts - self.prev_right_counts
                
                # Check for large jumps/resets
                if abs(delta_left) > self.reset_threshold or abs(delta_right) > self.reset_threshold:
                    self.get_logger().warn(f"Encoder jump detected (L: {delta_left}, R: {delta_right}). Re-initializing previous counts.")
                    self.prev_left_counts = left_counts
                    self.prev_right_counts = right_counts
                    return
                
                # Update previous
                self.prev_left_counts = left_counts
                self.prev_right_counts = right_counts
                
                # Distances covered by wheels (meters)
                d_left = (delta_left / self.counts_per_rev) * (2.0 * math.pi * self.wheel_radius)
                d_right = (delta_right / self.counts_per_rev) * (2.0 * math.pi * self.wheel_radius)
                
                # Center distance and rotation
                d_center = (d_left + d_right) / 2.0
                d_theta = (d_right - d_left) / self.track_width
                
                # Update pose
                self.x += d_center * math.cos(self.theta + (d_theta / 2.0))
                self.y += d_center * math.sin(self.theta + (d_theta / 2.0))
                self.theta += d_theta
                
                now = self.get_clock().now().to_msg()
                
                q = self.euler_to_quaternion(0, 0, self.theta)
                
                # Publish TF
                t = TransformStamped()
                t.header.stamp = now
                t.header.frame_id = 'odom'
                t.child_frame_id = 'base_link'
                t.transform.translation.x = self.x
                t.transform.translation.y = self.y
                t.transform.translation.z = 0.0
                t.transform.rotation.x = q[0]
                t.transform.rotation.y = q[1]
                t.transform.rotation.z = q[2]
                t.transform.rotation.w = q[3]
                self.tf_broadcaster.sendTransform(t)
                
                # Publish Odometry
                odom = Odometry()
                odom.header.stamp = now
                odom.header.frame_id = 'odom'
                odom.child_frame_id = 'base_link'
                odom.pose.pose.position.x = self.x
                odom.pose.pose.position.y = self.y
                odom.pose.pose.position.z = 0.0
                odom.pose.pose.orientation.x = q[0]
                odom.pose.pose.orientation.y = q[1]
                odom.pose.pose.orientation.z = q[2]
                odom.pose.pose.orientation.w = q[3]
                
                # Since we don't have time deltas for velocity, we won't populate twist
                # If time is available from msg, we could, but tracking position is primary
                
                self.odom_pub.publish(odom)
                
        except json.JSONDecodeError:
            self.get_logger().error("Failed to parse JSON from /esp32/data")
        except KeyError as e:
            self.get_logger().error(f"Missing key in JSON: {e}")
        except Exception as e:
            self.get_logger().error(f"Exception processing /esp32/data: {e}")

def main(args=None):
    rclpy.init(args=args)
    node = WheelOdom()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()

if __name__ == '__main__':
    main()
