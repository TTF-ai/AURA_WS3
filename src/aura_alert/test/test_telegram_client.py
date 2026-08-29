from unittest.mock import MagicMock, patch

from aura_alert.telegram_client import TelegramClient


@patch('httpx.Client')
def test_test_connection_success(mock_client_class):
    # Mocking the client instance and its get method
    mock_client = MagicMock()
    mock_client_class.return_value.__enter__.return_value = mock_client

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {'ok': True, 'result': {'username': 'AuraRobotBot'}}
    mock_client.get.return_value = mock_response

    client = TelegramClient(token='fake_token', chat_id='fake_chat_id')
    assert client.test_connection() is True
    mock_client.get.assert_called_once_with('https://api.telegram.org/botfake_token/getMe')


@patch('httpx.Client')
def test_test_connection_failure(mock_client_class):
    mock_client = MagicMock()
    mock_client_class.return_value.__enter__.return_value = mock_client

    mock_response = MagicMock()
    mock_response.status_code = 401
    mock_client.get.return_value = mock_response

    client = TelegramClient(token='fake_token', chat_id='fake_chat_id')
    assert client.test_connection() is False


@patch('httpx.Client')
def test_send_message_success(mock_client_class):
    mock_client = MagicMock()
    mock_client_class.return_value.__enter__.return_value = mock_client

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {'ok': True, 'result': {'message_id': 123}}
    mock_client.post.return_value = mock_response

    client = TelegramClient(token='fake_token', chat_id='fake_chat_id')
    res = client.send_message('Hello World')
    assert res is not None
    assert res['ok'] is True
    assert res['result']['message_id'] == 123
