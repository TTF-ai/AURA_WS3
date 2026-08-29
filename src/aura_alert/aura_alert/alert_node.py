import os
import threading

from aura_alert_msgs.msg import AlertStatus
from aura_behavior_msgs.msg import BehaviorEvent
from aura_face_msgs.msg import AuthenticationStatus

import rclpy
from rclpy.node import Node

from sensor_msgs.msg import Image
from std_srvs.srv import Trigger

from .alert_state import AlertState
from .event_handler import EventHandler
from .image_capture import ImageCapture
from .telegram_client import TelegramClient


class AlertNode(Node):
    """ROS 2 Node for managing the AURA Emergency Alert system."""

    def __init__(self):
        super().__init__('alert_node')

        # -------------------------------------------------------
        # Parameters
        # -------------------------------------------------------
        self.declare_parameter('telegram_enabled', True)
        self.declare_parameter('robot_location', 'Living Room')
        self.declare_parameter('alert_cooldown_seconds', 60.0)
        self.declare_parameter('max_retries', 3)
        self.declare_parameter('retry_delay_seconds', 2.0)
        self.declare_parameter('image_wait_timeout_seconds', 1.0)
        self.declare_parameter('image_quality', 85)
        self.declare_parameter('frame_buffer_seconds', 3.0)
        self.declare_parameter('send_photo', True)
        self.declare_parameter('send_text_fallback', True)
        self.declare_parameter('test_telegram_on_startup', True)

        # -------------------------------------------------------
        # State
        # -------------------------------------------------------
        self.authenticated = False
        self.auth_username = 'Authorized User'

        # -------------------------------------------------------
        # Components
        # -------------------------------------------------------
        token = os.environ.get('TELEGRAM_BOT_TOKEN', '')
        chat_id = os.environ.get('TELEGRAM_CHAT_ID', '')

        self.tg = TelegramClient(token, chat_id, logger=self.get_logger())
        self.ic = ImageCapture(
            frame_buffer_seconds=self.get_parameter('frame_buffer_seconds').value
        )
        self.alert_state = AlertState(
            cooldown_seconds=self.get_parameter('alert_cooldown_seconds').value
        )
        self.handler = EventHandler(self, self.tg, self.ic, self.alert_state)

        # -------------------------------------------------------
        # Publishers & Services
        # -------------------------------------------------------
        self.status_pub = self.create_publisher(AlertStatus, '/alert/status', 10)
        self.test_srv = self.create_service(Trigger, '/aura_alert/test', self.test_callback)

        # -------------------------------------------------------
        # Subscribers
        # -------------------------------------------------------
        self.image_sub = self.create_subscription(
            Image, '/camera/image_raw', self.image_callback, 10
        )
        self.auth_sub = self.create_subscription(
            AuthenticationStatus, '/auth/status', self.auth_callback, 10
        )
        self.event_sub = self.create_subscription(
            BehaviorEvent, '/behavior/event', self.behavior_event_callback, 10
        )

        # Startup test
        if self.get_parameter('test_telegram_on_startup').value:
            threading.Thread(target=self._startup_connection_test, daemon=True).start()

    def _startup_connection_test(self):
        """Asynchronously test the Telegram connection at startup."""
        if not self.get_parameter('telegram_enabled').value:
            self.get_logger().info('Telegram alerts are disabled in configuration.')
            return

        success = self.tg.test_connection()
        if success:
            self.get_logger().info('Telegram client successfully initialized and verified.')
            self.publish_status('IDLE', 'STARTUP', False, False, '', '')
        else:
            self.get_logger().error('Telegram client verification failed on startup.')
            self.publish_status(
                'ERROR', 'STARTUP_FAILED', False, False, 'Telegram unreachable', ''
            )

    # =============================================================
    # CALLBACKS
    # =============================================================

    def image_callback(self, msg: Image):
        """Buffer camera frames in memory."""
        self.ic.add_image(msg)

    def auth_callback(self, msg: AuthenticationStatus):
        """Track user authentication status and name."""
        self.authenticated = msg.authenticated
        self.auth_username = msg.username if msg.authenticated else 'Authorized User'

    def behavior_event_callback(self, msg: BehaviorEvent):
        """Receive behavioral classification updates and falls."""
        # Update current behavior state for cooldown reset / recovery detection
        if msg.behavior:
            self.alert_state.update_behavior(msg.behavior)

        # React only to FALL_CONFIRMED
        if msg.event_type == 'FALL_CONFIRMED':
            location = self.get_parameter('robot_location').value
            severity = msg.severity if msg.severity else 'HIGH'

            # Convert ROS stamp to epoch seconds
            stamp_sec = msg.header.stamp.sec + (msg.header.stamp.nanosec * 1e-9)

            # Run the alert in a separate thread so it doesn't block the ROS executor
            threading.Thread(
                target=self.handler.handle_fall_event,
                args=(self.auth_username, severity, location, stamp_sec),
                daemon=True
            ).start()

    def test_callback(self, request, response):
        """Handle manual test alert service call."""
        location = self.get_parameter('robot_location').value

        # Run test alert in background thread to avoid blocking service server
        def run_test():
            self.handler.handle_test_alert(location)

        threading.Thread(target=run_test, daemon=True).start()

        response.success = True
        response.message = 'Test alert triggered. Check Telegram group.'
        return response

    # =============================================================
    # STATUS PUBLISHING
    # =============================================================

    def publish_status(
        self,
        state: str,
        event_type: str,
        telegram_sent: bool,
        image_sent: bool,
        error_message: str,
        message_id: str
    ):
        """Publish node status to /alert/status."""
        msg = AlertStatus()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.state = state
        msg.event_type = event_type
        msg.telegram_sent = telegram_sent
        msg.image_sent = image_sent
        msg.error_message = error_message
        msg.message_id = message_id

        self.status_pub.publish(msg)


def main(args=None):
    """Run the main entrypoint for the alert node."""
    rclpy.init(args=args)
    node = AlertNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
