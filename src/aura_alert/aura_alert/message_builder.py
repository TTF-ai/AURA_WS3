import datetime


class MessageBuilder:
    """Builds emergency and test messages for AURA alerts."""

    @staticmethod
    def build_emergency_message(
        user_name: str,
        severity: str,
        location: str,
        timestamp_sec: float = None
    ) -> str:
        """Build a formatted emergency message for fall detection."""
        if timestamp_sec:
            dt = datetime.datetime.fromtimestamp(timestamp_sec)
        else:
            dt = datetime.datetime.now()

        formatted_time = dt.strftime('%d %b %Y, %I:%M:%S %p')

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
        dt = datetime.datetime.now()
        formatted_time = dt.strftime('%d %b %Y, %I:%M:%S %p')

        message = (
            '🧪 <b>AURA TEST ALERT</b>\n\n'
            'Telegram notification system is working.\n\n'
            f'<b>Location:</b> {location}\n'
            f'<b>Time:</b> {formatted_time}\n'
        )
        return message
