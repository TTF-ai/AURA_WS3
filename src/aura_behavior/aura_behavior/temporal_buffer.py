import time


class TemporalBuffer:
    """Time-based temporal buffer for behavior features.

    Stores feature observations and automatically expires entries
    older than `max_age_seconds`.  This prevents stale history from
    contaminating current classifications.
    """

    def __init__(self, size=30, max_age_seconds=1.0):
        self.size = size
        self.max_age_seconds = max_age_seconds
        self.buffer = []

    def append(self, features):
        """Add a feature dict.  Prunes stale entries first."""
        self._prune()
        self.buffer.append(features)
        # Hard cap on buffer length as a safety net
        if len(self.buffer) > self.size:
            self.buffer.pop(0)

    def clear(self):
        self.buffer.clear()

    def get_recent(self, n=None):
        """Return the most recent *n* entries within the time window."""
        self._prune()
        if n is None or n >= len(self.buffer):
            return list(self.buffer)
        return list(self.buffer[-n:])

    def _prune(self):
        """Remove entries older than max_age_seconds."""
        if not self.buffer:
            return
        cutoff = time.time() - self.max_age_seconds
        self.buffer = [f for f in self.buffer if f.get('timestamp', 0) >= cutoff]

    def is_full(self):
        return len(self.buffer) >= self.size

    def is_empty(self):
        return len(self.buffer) == 0
