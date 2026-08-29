from aura_alert.message_builder import MessageBuilder


def test_build_emergency_message():
    user = 'Thirumalesh'
    severity = 'CRITICAL'
    location = 'Living Room'
    timestamp_sec = 1786431399.0

    msg = MessageBuilder.build_emergency_message(user, severity, location, timestamp_sec)

    assert 'AURA EMERGENCY ALERT' in msg
    assert 'Possible fall detected.' in msg
    assert 'Person:</b> Thirumalesh' in msg
    assert 'Severity:</b> CRITICAL' in msg
    assert 'Location:</b> Living Room' in msg


def test_build_test_message():
    location = 'Kitchen'
    msg = MessageBuilder.build_test_message(location)

    assert 'AURA TEST ALERT' in msg
    assert 'Telegram notification system is working.' in msg
    assert 'Location:</b> Kitchen' in msg
