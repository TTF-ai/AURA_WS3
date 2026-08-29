import numpy as np
import time


def extract_keypoints(keypoints):
    """
    Extracts essential points from YOLOv8 / MediaPipe pose format.
    YOLOv8 format (17 keypoints):
    0: Nose, 1: L-Eye, 2: R-Eye, 3: L-Ear, 4: R-Ear
    5: L-Shoulder, 6: R-Shoulder, 7: L-Elbow, 8: R-Elbow
    9: L-Wrist, 10: R-Wrist, 11: L-Hip, 12: R-Hip
    13: L-Knee, 14: R-Knee, 15: L-Ankle, 16: R-Ankle
    """
    def get_pt(idx):
        # returns [x, y] or None if confidence is too low
        if keypoints[idx][2] > 0.3:
            return keypoints[idx][:2]
        return None

    def get_center(idx1, idx2):
        pt1 = get_pt(idx1)
        pt2 = get_pt(idx2)
        if pt1 is not None and pt2 is not None:
            return (pt1 + pt2) / 2.0
        elif pt1 is not None:
            return pt1
        elif pt2 is not None:
            return pt2
        return None

    head = get_pt(0)
    l_shoulder = get_pt(5)
    r_shoulder = get_pt(6)
    shoulder = get_center(5, 6)
    l_hip = get_pt(11)
    r_hip = get_pt(12)
    hip = get_center(11, 12)
    l_knee = get_pt(13)
    r_knee = get_pt(14)
    knee = get_center(13, 14)
    l_ankle = get_pt(15)
    r_ankle = get_pt(16)
    ankle = get_center(15, 16)
    l_wrist = get_pt(9)
    r_wrist = get_pt(10)

    return {
        'head': head,
        'l_shoulder': l_shoulder,
        'r_shoulder': r_shoulder,
        'shoulder': shoulder,
        'l_hip': l_hip,
        'r_hip': r_hip,
        'hip': hip,
        'l_knee': l_knee,
        'r_knee': r_knee,
        'knee': knee,
        'l_ankle': l_ankle,
        'r_ankle': r_ankle,
        'ankle': ankle,
        'l_wrist': l_wrist,
        'r_wrist': r_wrist,
    }


def _count_valid_points(points):
    """Count how many keypoint groups are non-None."""
    core_keys = ['shoulder', 'hip']
    optional_keys = ['head', 'knee', 'ankle', 'l_wrist', 'r_wrist']
    count = 0
    for k in core_keys + optional_keys:
        if points.get(k) is not None:
            count += 1
    return count


def calculate_features(points, target_bbox):
    """
    Calculate high-level features for behavior classification.
    Uses keypoint geometry (not bounding box) for more accurate
    body-state estimation.
    """
    features = {
        'timestamp': time.time(),
        'body_angle': None,
        'body_height': None,
        'vertical_ratio': None,
        'hip_knee_angle': None,
        'center_x': None,
        'center_y': None,
        'shoulder_hip_dist': None,
        'hip_knee_dist': None,
        'valid': False,
        'valid_point_count': 0,
    }

    shoulder = points['shoulder']
    hip = points['hip']
    head = points['head']
    knee = points['knee']
    ankle = points['ankle']

    features['valid_point_count'] = _count_valid_points(points)

    # Need at least shoulders and hips for any meaningful classification
    if shoulder is None or hip is None:
        return features

    # --- Torso angle (0° = upright vertical, 90° = horizontal) ---
    dx = abs(shoulder[0] - hip[0])
    dy = abs(shoulder[1] - hip[1])
    if dy == 0:
        features['body_angle'] = 90.0
    else:
        features['body_angle'] = np.degrees(np.arctan(dx / dy))

    # --- Shoulder-to-hip distance (pixel space) ---
    sh_dist = np.sqrt((shoulder[0] - hip[0])**2 + (shoulder[1] - hip[1])**2)
    features['shoulder_hip_dist'] = float(sh_dist)

    # --- Vertical ratio from keypoints (not bounding box) ---
    # Use highest point to lowest point for true body aspect ratio
    top_y = shoulder[1]
    bottom_y = hip[1]

    if head is not None:
        top_y = min(top_y, head[1])
    if ankle is not None:
        bottom_y = max(bottom_y, ankle[1])
    elif knee is not None:
        bottom_y = max(bottom_y, knee[1])

    body_height = abs(bottom_y - top_y)
    features['body_height'] = float(body_height)

    # Vertical ratio: tall body = standing, short body = sitting/lying
    # Using keypoint-based width for more accurate ratio
    body_width = max(1.0, abs(shoulder[0] - hip[0]))
    if points.get('l_shoulder') is not None and points.get('r_shoulder') is not None:
        body_width = max(body_width, abs(points['l_shoulder'][0] - points['r_shoulder'][0]))

    features['vertical_ratio'] = body_height / max(1.0, body_width)

    # --- Hip-knee angle for sitting detection ---
    if hip is not None and knee is not None:
        hk_dx = abs(hip[0] - knee[0])
        hk_dy = abs(hip[1] - knee[1])
        if hk_dy == 0:
            features['hip_knee_angle'] = 90.0  # Knees at same height = sitting
        else:
            features['hip_knee_angle'] = np.degrees(np.arctan(hk_dx / hk_dy))

        hk_dist = np.sqrt((hip[0] - knee[0])**2 + (hip[1] - knee[1])**2)
        features['hip_knee_dist'] = float(hk_dist)

    # --- Center position for movement tracking ---
    if hip is not None:
        features['center_x'] = float(hip[0])
        features['center_y'] = float(hip[1])
    elif shoulder is not None:
        features['center_x'] = float(shoulder[0])
        features['center_y'] = float(shoulder[1])
    else:
        x1, y1, x2, y2 = target_bbox
        features['center_x'] = float((x1 + x2) / 2.0)
        features['center_y'] = float((y1 + y2) / 2.0)

    features['valid'] = True
    return features
