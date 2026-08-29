import logging
import os
import time

import httpx


class TelegramClient:
    """Official Telegram Bot API Client for AURA Emergency Alerts."""

    def __init__(self, token=None, chat_id=None, logger=None):
        self.token = token or os.environ.get('TELEGRAM_BOT_TOKEN', '')
        self.chat_id = chat_id or os.environ.get('TELEGRAM_CHAT_ID', '')
        self.logger = logger or logging.getLogger('TelegramClient')
        self.base_url = f'https://api.telegram.org/bot{self.token}'

    def is_configured(self) -> bool:
        """Check if both token and chat ID are provided."""
        return bool(self.token and self.chat_id)

    def test_connection(self) -> bool:
        """Validate bot credentials using getMe endpoint."""
        if not self.token:
            self.logger.warning('Telegram Bot Token is missing.')
            return False

        url = f'{self.base_url}/getMe'
        try:
            with httpx.Client(timeout=10.0) as client:
                response = client.get(url)
                if response.status_code == 200:
                    bot_info = response.json()
                    if bot_info.get('ok'):
                        username = bot_info['result'].get('username', 'UnknownBot')
                        self.logger.info(f'Telegram connection verified. Bot: @{username}')
                        return True
                self.logger.error(
                    f'Telegram verification failed. Status code: {response.status_code}'
                )
                return False
        except Exception as e:
            self.logger.error(f'Failed to connect to Telegram API: {e}')
            return False

    def send_message(self, text: str, max_retries: int = 3, retry_delay: float = 2.0) -> dict:
        """Send a text message via Telegram sendMessage API."""
        if not self.is_configured():
            self.logger.error('Telegram client is not fully configured.')
            return None

        url = f'{self.base_url}/sendMessage'
        payload = {
            'chat_id': self.chat_id,
            'text': text,
            'parse_mode': 'HTML'
        }

        for attempt in range(max_retries):
            try:
                with httpx.Client(timeout=10.0) as client:
                    response = client.post(url, json=payload)
                    if response.status_code == 200:
                        res_json = response.json()
                        if res_json.get('ok'):
                            return res_json
                    self.logger.warning(
                        f'Failed to send message (Attempt {attempt+1}/{max_retries}). '
                        f'HTTP Status: {response.status_code}'
                    )
            except Exception as e:
                self.logger.warning(
                    f'Error sending message (Attempt {attempt+1}/{max_retries}): {e}'
                )

            if attempt < max_retries - 1:
                time.sleep(retry_delay)

        self.logger.error('Failed to send text message after all retries.')
        return None

    def send_photo(
        self,
        photo_bytes: bytes,
        caption: str,
        max_retries: int = 3,
        retry_delay: float = 2.0
    ) -> dict:
        """Send a photo with a caption via Telegram sendPhoto API."""
        if not self.is_configured():
            self.logger.error('Telegram client is not fully configured.')
            return None

        url = f'{self.base_url}/sendPhoto'
        data = {
            'chat_id': self.chat_id,
            'caption': caption,
            'parse_mode': 'HTML'
        }
        files = {
            'photo': ('fall_event.jpg', photo_bytes, 'image/jpeg')
        }

        for attempt in range(max_retries):
            try:
                with httpx.Client(timeout=15.0) as client:
                    response = client.post(url, data=data, files=files)
                    if response.status_code == 200:
                        res_json = response.json()
                        if res_json.get('ok'):
                            return res_json
                    self.logger.warning(
                        f'Failed to send photo (Attempt {attempt+1}/{max_retries}). '
                        f'HTTP Status: {response.status_code}'
                    )
            except Exception as e:
                self.logger.warning(
                    f'Error sending photo (Attempt {attempt+1}/{max_retries}): {e}'
                )

            if attempt < max_retries - 1:
                time.sleep(retry_delay)

        self.logger.error('Failed to send photo alert after all retries.')
        return None
