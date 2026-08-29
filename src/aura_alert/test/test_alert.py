import time

from aura_alert.alert_state import AlertState


def test_alert_state_machine():
    state = AlertState(cooldown_seconds=1.0)

    # Init state
    assert state.state == AlertState.IDLE
    assert state.can_trigger() is True

    # Trigger
    state.trigger()
    assert state.state == AlertState.ALERTING

    # Mark sent -> moves to COOLDOWN
    state.mark_sent()
    assert state.state == AlertState.COOLDOWN
    assert state.can_trigger() is False

    # Wait for cooldown
    time.sleep(1.1)
    assert state.can_trigger() is True
    assert state.state == AlertState.IDLE


def test_recovery_reset():
    state = AlertState(cooldown_seconds=60.0)

    state.trigger()
    state.mark_sent()
    assert state.state == AlertState.COOLDOWN
    assert state.can_trigger() is False

    # Update behavior to STANDING -> should reset to IDLE immediately
    state.update_behavior('STANDING')
    assert state.state == AlertState.IDLE
    assert state.can_trigger() is True
