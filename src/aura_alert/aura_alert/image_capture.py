import collections
import time

import cv2

from cv_bridge import CvBridge

from sensor_msgs.msg import Image


class ImageCapture:
    """Manages an in-memory buffer of camera frames for fall evidence capture."""

    def __init__(self, frame_buffer_seconds: float = 3.0):
        self.frame_buffer_seconds = frame_buffer_seconds
        # Double-ended queue storing tuples: (timestamp, cv2_frame)
        self.buffer = collections.deque()
        self.bridge = CvBridge()

    def add_image(self, msg: Image):
        """Convert ROS image and add it to the buffer with the current timestamp."""
        try:
            now = time.time()
            cv_img = self.bridge.imgmsg_to_cv2(msg, desired_encoding='bgr8')

            self.buffer.append((now, cv_img))

            # Clean up old frames outside the buffer window
            while self.buffer and (now - self.buffer[0][0] > self.frame_buffer_seconds):
                self.buffer.popleft()

        except Exception:
            # Silently catch conversion errors to avoid disrupting subscription
            pass

    def get_best_frame(self, target_timestamp: float = None, quality: int = 85) -> bytes:
        """Retrieve the closest buffered frame encoded as JPEG bytes."""
        if not self.buffer:
            return None

        selected_frame = None

        if target_timestamp is None:
            # Return the latest frame
            selected_frame = self.buffer[-1][1]
        else:
            # Find the frame closest to target_timestamp
            closest_diff = float('inf')
            for ts, frame in self.buffer:
                diff = abs(ts - target_timestamp)
                if diff < closest_diff:
                    closest_diff = diff
                    selected_frame = frame

        if selected_frame is None:
            return None

        # Encode to JPEG
        success, encoded_img = cv2.imencode(
            '.jpg', selected_frame, [int(cv2.IMWRITE_JPEG_QUALITY), quality]
        )
        if success:
            return encoded_img.tobytes()
        return None
