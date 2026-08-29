import time

from .alert_state import AlertState
from .image_capture import ImageCapture
from .message_builder import MessageBuilder
from .telegram_client import TelegramClient


class EventHandler:
    """Coordinating handler for emergency alerts and tests."""

    def __init__(
        self,
        node,
        telegram_client: TelegramClient,
        image_capture: ImageCapture,
        alert_state: AlertState
    ):
        self.node = node
        self.tg = telegram_client
        self.ic = image_capture
        self.state = alert_state

    def handle_fall_event(
        self,
        user_name: str,
        severity: str,
        location: str,
        timestamp_sec: float = None
    ):
        """Coordinate the alert pipeline when a fall is confirmed."""
        # 1. State/cooldown check
        if not self.state.can_trigger():
            self.node.get_logger().info('Alert request ignored: cooldown active or not IDLE.')
            return

        self.node.get_logger().info(
            f'🚨 Handling fall event for user {user_name} at {location}...'
        )
        self.state.trigger()

        # Publish ALERTING status
        self.node.publish_status(self.state.state, 'FALL_CONFIRMED', False, False, '', '')

        # 2. Get frame wait timeout
        wait_timeout = self.node.get_parameter('image_wait_timeout_seconds').value
        image_quality = self.node.get_parameter('image_quality').value

        start_wait = time.time()
        photo_bytes = None
        while time.time() - start_wait < wait_timeout:
            photo_bytes = self.ic.get_best_frame(timestamp_sec, quality=image_quality)
            if photo_bytes:
                break
            time.sleep(0.1)

        # 3. Build caption/message
        caption = MessageBuilder.build_emergency_message(
            user_name, severity, location, timestamp_sec
        )

        # 4. Attempt to send
        send_photo_enabled = self.node.get_parameter('send_photo').value
        max_retries = self.node.get_parameter('max_retries').value
        retry_delay = self.node.get_parameter('retry_delay_seconds').value

        telegram_sent = False
        image_sent = False
        error_message = ''
        message_id = ''

        if photo_bytes and send_photo_enabled:
            # Send photo with caption
            res = self.tg.send_photo(
                photo_bytes, caption, max_retries=max_retries, retry_delay=retry_delay
            )
            if res and res.get('ok'):
                telegram_sent = True
                image_sent = True
                message_id = str(res['result'].get('message_id', ''))
            else:
                error_message = 'Failed to send photo'

        # Fallback to text message if photo failed or was disabled/unavailable
        if not telegram_sent and self.node.get_parameter('send_text_fallback').value:
            res = self.tg.send_message(caption, max_retries=max_retries, retry_delay=retry_delay)
            if res and res.get('ok'):
                telegram_sent = True
                message_id = str(res['result'].get('message_id', ''))
            else:
                error_message = f'Failed to send text. (Photo error: {error_message})'

        # 5. Update state machine
        if telegram_sent:
            self.state.mark_sent()
            self.node.get_logger().info(
                f'Alert successfully sent to Telegram. Msg ID: {message_id}'
            )
        else:
            self.state.mark_failed()
            self.node.get_logger().error(f'Alert failed to send: {error_message}')

        # 6. Publish final status
        self.node.publish_status(
            self.state.state,
            'FALL_CONFIRMED',
            telegram_sent,
            image_sent,
            error_message,
            message_id
        )

    def handle_test_alert(self, location: str) -> bool:
        """Coordinate the alert pipeline for manual test service."""
        self.node.get_logger().info('🧪 Triggering manual alert system test...')

        # Get frame
        image_quality = self.node.get_parameter('image_quality').value
        photo_bytes = self.ic.get_best_frame(quality=image_quality)

        # Build message
        caption = MessageBuilder.build_test_message(location)

        # Send
        max_retries = self.node.get_parameter('max_retries').value
        retry_delay = self.node.get_parameter('retry_delay_seconds').value
        send_photo_enabled = self.node.get_parameter('send_photo').value

        telegram_sent = False
        message_id = ''

        if photo_bytes and send_photo_enabled:
            res = self.tg.send_photo(
                photo_bytes, caption, max_retries=max_retries, retry_delay=retry_delay
            )
            if res and res.get('ok'):
                telegram_sent = True
                message_id = str(res['result'].get('message_id', ''))

        if not telegram_sent:
            res = self.tg.send_message(caption, max_retries=max_retries, retry_delay=retry_delay)
            if res and res.get('ok'):
                telegram_sent = True
                message_id = str(res['result'].get('message_id', ''))

        if telegram_sent:
            self.node.get_logger().info(
                f'Test alert successfully sent to Telegram. Msg ID: {message_id}'
            )
            return True
        else:
            self.node.get_logger().error('Test alert failed to send.')
            return False
