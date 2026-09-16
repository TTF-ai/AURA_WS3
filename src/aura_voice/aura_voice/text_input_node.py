#!/usr/bin/env python3

import sys

import rclpy
from rclpy.node import Node
from std_msgs.msg import String


class TextInputNode(Node):
    """Simple text test node for sending commands into the voice pipeline."""

    def __init__(self):
        super().__init__('text_input_node')
        self.pub = self.create_publisher(String, '/voice/text_input', 10)
        self._prompt_text = "\nType a command and press Enter.\nExamples:\n  aura tell me the weather\n  aura follow me\n  aura stop following\n  quit\n> "
        self.get_logger().info('Text input node ready. Publish to /voice/text_input')

    def run_console(self):
        while rclpy.ok():
            try:
                user_text = input(self._prompt_text)
            except EOFError:
                return
            except KeyboardInterrupt:
                return

            text = (user_text or '').strip()
            if not text:
                continue
            if text.lower() in {'quit', 'exit'}:
                self.get_logger().info('Exiting text input node.')
                return

            msg = String()
            msg.data = text
            self.pub.publish(msg)
            self.get_logger().info(f'Published text input: "{text}"')


def main(args=None):
    rclpy.init(args=args)
    node = TextInputNode()
    try:
        node.run_console()
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
