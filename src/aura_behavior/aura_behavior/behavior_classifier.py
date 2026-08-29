class BehaviorClassifier:
    """
    Classifies current behavior using keypoint geometry and short hysteresis.

    Uses a confirmation mechanism: a new candidate behavior must persist
    for `confirmation_frames` consecutive observations before the published
    behavior transitions.  This prevents flicker without the multi-second
    lag of long majority-voting buffers.
    """

    def __init__(self, params):
        self.params = params

        # Hysteresis state
        self.current_behavior = "UNKNOWN"
        self.candidate_behavior = "UNKNOWN"
        self.candidate_count = 0
        self.confirmation_frames = params.get('behavior_confirmation_frames', 3)

    def classify(self, features_history):
        """
        Classifies behavior into STANDING, WALKING, SITTING, LYING, UNKNOWN.
        features_history: list of feature dicts from TemporalBuffer (time-pruned)
        """
        if not features_history:
            return self.current_behavior, 0.0

        recent = [f for f in features_history if f['valid']]
        if not recent:
            return self.current_behavior, 0.0

        latest = recent[-1]

        # Need at least shoulders + hips (2 core points)
        min_points = self.params.get('min_valid_keypoints', 3)
        if latest.get('valid_point_count', 0) < min_points:
            return self.current_behavior, 0.0

        # --- Raw classification from geometry ---
        raw_behavior, raw_conf = self._classify_raw(latest, recent)

        # --- Hysteresis ---
        if raw_behavior == self.candidate_behavior:
            self.candidate_count += 1
        else:
            self.candidate_behavior = raw_behavior
            self.candidate_count = 1

        if self.candidate_count >= self.confirmation_frames:
            if self.candidate_behavior != self.current_behavior:
                self.current_behavior = self.candidate_behavior

        return self.current_behavior, raw_conf

    def _classify_raw(self, latest, recent):
        """Instantaneous classification from a single frame's features."""

        body_angle = latest.get('body_angle', 0.0)
        vert_ratio = latest.get('vertical_ratio', 2.0)
        hip_knee_angle = latest.get('hip_knee_angle')

        # -------------------------------------------------------
        # 1. LYING — body is nearly horizontal
        # -------------------------------------------------------
        lying_threshold = self.params.get('lying_body_angle_threshold', 55.0)
        if body_angle > lying_threshold:
            return "LYING", 0.85

        # Also detect lying by very low vertical ratio (body is flat)
        if vert_ratio < 0.7:
            return "LYING", 0.75

        # -------------------------------------------------------
        # 2. SITTING — hip-knee angle indicates bent legs, torso upright
        # -------------------------------------------------------
        if hip_knee_angle is not None and body_angle < 40.0:
            # When sitting, knees are typically at or above hip level
            # hip_knee_angle > 35° means legs are spread horizontally
            if hip_knee_angle > 35.0:
                return "SITTING", 0.80

        # Fallback sitting: short vertical ratio with upright torso
        if vert_ratio < 1.5 and body_angle < 40.0:
            return "SITTING", 0.70

        # -------------------------------------------------------
        # 3. STANDING vs WALKING — torso upright, tall body
        # -------------------------------------------------------
        if body_angle < 35.0:
            # Check for walking via horizontal center movement
            if len(recent) >= 3:
                movement = self._compute_movement(recent)
                walking_thresh = self.params.get('walking_min_movement', 8.0)
                if movement > walking_thresh:
                    return "WALKING", 0.80

            return "STANDING", 0.90

        return "UNKNOWN", 0.0

    def _compute_movement(self, recent):
        """
        Compute average horizontal + vertical center displacement
        over the recent time window.  Uses center_x to detect
        lateral walking, not just vertical bounce.
        """
        if len(recent) < 2:
            return 0.0

        # Use the earliest and latest in the window
        start = recent[0]
        end = recent[-1]

        dt = end.get('timestamp', 0) - start.get('timestamp', 0)
        if dt < 0.05:
            return 0.0

        dx = abs(end.get('center_x', 0) - start.get('center_x', 0))
        dy = abs(end.get('center_y', 0) - start.get('center_y', 0))

        # Combined displacement (pixels per second)
        displacement = (dx + dy) / dt
        return displacement

    def reset(self):
        """Reset hysteresis state."""
        self.current_behavior = "UNKNOWN"
        self.candidate_behavior = "UNKNOWN"
        self.candidate_count = 0
