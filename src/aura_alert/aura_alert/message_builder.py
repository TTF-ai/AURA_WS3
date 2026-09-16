import datetime


class MessageBuilder:
    """Builds emergency, test, and user-message messages for AURA alerts."""

    @staticmethod
    def _format_timestamp(timestamp_sec: float = None) -> str:
        """Return a consistent readable timestamp for Telegram alert messages."""
        dt = datetime.datetime.fromtimestamp(timestamp_sec) if timestamp_sec else datetime.datetime.now()
        return dt.strftime('%d %b %Y, %I:%M:%S %p')

    @staticmethod
    def build_emergency_message(
        user_name: str,
        severity: str,
        location: str,
        timestamp_sec: float = None
    ) -> str:
        """Build a formatted emergency message for fall detection."""
        formatted_time = MessageBuilder._format_timestamp(timestamp_sec)

        message = (
            '🚨 <b>AURA EMERGENCY ALERT</b>\n\n'
            'Possible fall detected.\n\n'
            f'<b>Person:</b> {user_name}\n'
            f'<b>Severity:</b> {severity}\n'
            '<b>Status:</b> Person remains down\n'
            f'<b>Time:</b> {formatted_time}\n'
            f'<b>Location:</b> {location}\n\n'
            '<i>Please check on the person immediately.</i>'
        )
        return message

    @staticmethod
    def build_test_message(location: str) -> str:
        """Build a formatted test message."""
        formatted_time = MessageBuilder._format_timestamp()

        message = (
            '🧪 <b>AURA TEST ALERT</b>\n\n'
            'Telegram notification system is working.\n\n'
            f'<b>Location:</b> {location}\n'
            f'<b>Time:</b> {formatted_time}\n'
        )
        return message

    @staticmethod
    def build_user_message(
        user_name: str,
        message_text: str,
        location: str,
        timestamp_sec: float = None
    ) -> str:
        """Build a formatted message from a user-spoken update for Telegram."""
        clean_text = (message_text or '').strip()
        if not clean_text:
            clean_text = 'No message content provided.'

        formatted_time = MessageBuilder._format_timestamp(timestamp_sec)

        return (
            '📨 <b>AURA USER MESSAGE</b>\n\n'
            f'<b>From:</b> {user_name}\n'
            f'<b>Location:</b> {location}\n'
            f'<b>Time:</b> {formatted_time}\n\n'
            '<b>Message:</b>\n'
            f'{clean_text}'
        )
