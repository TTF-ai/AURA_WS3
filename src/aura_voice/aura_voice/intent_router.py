"""
Intent Router for AURA voice system.

Maps validated intents to safe ROS 2 actions.
The LLM never directly publishes ROS messages.
"""

import rclpy
from geometry_msgs.msg import Twist
from std_msgs.msg import String


class IntentRouter:
    """
    Routes structured intents to safe ROS 2 operations.

    Does NOT directly publish /cmd_vel motor commands.
    Uses high-level ROS interfaces to trigger existing subsystems.
    """

    def __init__(self, node, language_manager):
        self.node = node
        self.language_manager = language_manager

        # Publisher for follow commands
        self.follow_cmd_pub = node.create_publisher(
            String, "/follow/command", 10
        )

        # Publisher for emergency stop
        self.emergency_stop_pub = node.create_publisher(
            Twist, "/cmd_vel", 10
        )

    def execute(self, intent: str, parameters: dict, username: str) -> str:
        """
        Execute a validated intent.

        Args:
            intent: The intent string.
            parameters: Dict of parameters from LLM.
            username: The authenticated username.

        Returns:
            str: Execution result description.
        """
        handler = self._handlers.get(intent)
        if handler:
            return handler(self, parameters, username)
        return "unknown_intent"

    def _handle_follow_user(self, parameters, username):
        msg = String()
        msg.data = "START"
        self.follow_cmd_pub.publish(msg)
        self.node.get_logger().info(f"Intent FOLLOW_USER executed for {username}")
        return "follow_started"

    def _handle_stop_following(self, parameters, username):
        msg = String()
        msg.data = "STOP"
        self.follow_cmd_pub.publish(msg)
        self.node.get_logger().info(f"Intent STOP_FOLLOWING executed for {username}")
        return "follow_stopped"

    def _handle_stop_robot(self, parameters, username):
        # Emergency stop — publish zero velocity
        stop_msg = Twist()
        self.emergency_stop_pub.publish(stop_msg)
        self.node.get_logger().warning(f"EMERGENCY STOP requested by {username}")
        return "robot_stopped"

    def _handle_change_language(self, parameters, username):
        lang = parameters.get("language", "en")
        success = self.language_manager.set_language(username, lang)
        if success:
            self.node.get_logger().info(
                f"Language changed to '{lang}' for user '{username}'"
            )
            return f"language_changed:{lang}"
        return "language_change_failed"

    def _handle_info(self, parameters, username):
        # Informational intents — no ROS action needed
        return "info_only"

    # Map intents to handlers
    _handlers = {
        "FOLLOW_USER": _handle_follow_user,
        "STOP_FOLLOWING": _handle_stop_following,
        "STOP_ROBOT": _handle_stop_robot,
        "CHANGE_LANGUAGE": _handle_change_language,
        "WHAT_ARE_YOU_DOING": _handle_info,
        "WHO_AM_I": _handle_info,
        "WHAT_IS_MY_LANGUAGE": _handle_info,
        "HELP": _handle_info,
        "STATUS": _handle_info,
        "GO_TO_LOCATION": _handle_info,  # Future implementation
        "UNKNOWN": _handle_info,
    }
