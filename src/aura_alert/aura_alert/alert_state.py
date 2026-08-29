import time


class AlertState:
    """Manages the state machine and cooldown logic for AURA alerts."""

    # States
    IDLE = 'IDLE'
    ALERTING = 'ALERTING'
    ALERT_SENT = 'ALERT_SENT'
    COOLDOWN = 'COOLDOWN'
    ERROR = 'ERROR'

    def __init__(self, cooldown_seconds: float = 60.0):
        self.state = self.IDLE
        self.cooldown_seconds = cooldown_seconds
        self.last_alert_time = 0.0
        self.current_behavior = 'UNKNOWN'

    def update_behavior(self, behavior: str):
        """Update current behavior state and handle recovery transitions."""
        self.current_behavior = behavior

        # Recovery detection: if the user gets back up (not FALL or UNKNOWN), reset to IDLE
        if self.state in [self.ALERT_SENT, self.COOLDOWN]:
            if behavior in ['STANDING', 'WALKING', 'SITTING', 'LYING']:
                self.reset()

    def can_trigger(self) -> bool:
        """Check if an alert can be triggered right now."""
        now = time.time()

        # If in COOLDOWN, check if cooldown time has elapsed
        if self.state == self.COOLDOWN:
            if now - self.last_alert_time >= self.cooldown_seconds:
                self.state = self.IDLE

        return self.state == self.IDLE

    def trigger(self):
        """Move state to ALERTING."""
        if self.can_trigger():
            self.state = self.ALERTING

    def mark_sent(self):
        """Move state to ALERT_SENT and record time, then transition to COOLDOWN."""
        self.state = self.ALERT_SENT
        self.last_alert_time = time.time()
        self.state = self.COOLDOWN

    def mark_failed(self):
        """Transition to ERROR on failure."""
        self.state = self.ERROR

    def reset(self):
        """Reset state back to IDLE."""
        self.state = self.IDLE
