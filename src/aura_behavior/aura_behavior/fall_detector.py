import time


class FallDetector:
    """
    Fall detection state machine.

    Uses a separate, longer temporal window than normal behavior
    classification.  Normal behavior uses ~1s history; fall verification
    uses its own configurable window (default 2.0s) to avoid false
    positives from momentary body-angle spikes.

    States: NORMAL → FALL_SUSPECTED → VERIFYING → FALL_CONFIRMED
    """

    def __init__(self, params):
        self.params = params
        self.state = "NORMAL"  # NORMAL, FALL_SUSPECTED, VERIFYING, FALL_CONFIRMED
        self.suspected_time = 0.0
        self.last_event_time = 0.0

    def update(self, features_history):
        """
        Updates fall state machine based on temporal features.
        Returns:
            event_to_publish: string or None (e.g., 'FALL_SUSPECTED', 'FALL_CONFIRMED', 'FALL_CANCELLED')
        """
        now = time.time()

        if not features_history:
            return None

        recent = [f for f in features_history if f['valid']]
        if len(recent) < 2:
            return None

        latest = recent[-1]

        # 1. Check for rapid downward movement + angle change (Suspect a fall)
        if self.state == "NORMAL":
            if now - self.last_event_time < self.params.get('event_cooldown_seconds', 10.0):
                return None  # Cooldown active

            # Compare latest with the earliest observation in the window
            past = recent[0]

            dt = latest['timestamp'] - past['timestamp']
            if dt > 0.1:  # Need at least 100ms of data
                dy = latest.get('center_y', 0) - past.get('center_y', 0)
                vy = dy / dt

                # If they moved down rapidly and angle became large
                if vy > self.params.get('fall_min_vertical_velocity', 200.0) and \
                   latest.get('body_angle', 0) > self.params.get('fall_body_angle_threshold', 50.0):

                    self.state = "FALL_SUSPECTED"
                    self.suspected_time = now
                    return "FALL_SUSPECTED"

        # 2. Transition from SUSPECTED to VERIFYING
        elif self.state == "FALL_SUSPECTED":
            self.state = "VERIFYING"

        # 3. Verify the fall
        elif self.state == "VERIFYING":
            elapsed = now - self.suspected_time

            # Did they get back up?
            if latest.get('body_angle', 0) < 30.0 and latest.get('vertical_ratio', 2.0) > 1.5:
                self.state = "NORMAL"
                return "FALL_CANCELLED"

            # Verification time passed
            if elapsed > self.params.get('fall_verification_seconds', 2.0):
                # Still down?
                if latest.get('body_angle', 0) > self.params.get('fall_body_angle_threshold', 50.0):
                    self.state = "FALL_CONFIRMED"
                    self.last_event_time = now
                    return "FALL_CONFIRMED"
                else:
                    self.state = "NORMAL"
                    return "FALL_CANCELLED"

        # 4. Stay in CONFIRMED until recovered
        elif self.state == "FALL_CONFIRMED":
            if latest.get('body_angle', 0) < 30.0 and latest.get('vertical_ratio', 2.0) > 1.5:
                self.state = "NORMAL"

        return None

    def reset(self):
        self.state = "NORMAL"
        self.suspected_time = 0.0
