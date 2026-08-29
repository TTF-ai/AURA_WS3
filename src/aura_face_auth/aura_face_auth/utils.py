"""
Shared utility functions for AURA face authentication.

No ROS imports in this file.
Pure numpy/OpenCV functions only.
"""

import cv2
import numpy as np


# =================================================================
# STANDARD ARCFACE ALIGNMENT REFERENCE POINTS
# =================================================================
# Reference landmarks for a 112x112 aligned face image.
# Based on the standard ArcFace alignment template.

ARCFACE_REF_LANDMARKS = np.array([
    [38.2946, 51.6963],   # left eye
    [73.5318, 51.5014],   # right eye
    [56.0252, 71.7366],   # nose
    [41.5493, 92.3655],   # left mouth
    [70.7299, 92.2041],   # right mouth
], dtype=np.float32)


# =================================================================
# EMBEDDING OPERATIONS
# =================================================================

def normalize_embedding(embedding):
    """
    L2 normalize an embedding vector to unit length.

    Args:
        embedding: numpy array (e.g. 512-d)

    Returns:
        Normalized numpy array with L2 norm = 1.0.
        Returns zero vector if input norm is zero.
    """
    embedding = np.asarray(embedding, dtype=np.float32)
    norm = np.linalg.norm(embedding)

    if norm < 1e-10:
        return np.zeros_like(embedding)

    return embedding / norm


def cosine_similarity(a, b):
    """
    Compute cosine similarity between two embedding vectors.

    Both vectors should be L2-normalized for accurate results.

    Args:
        a: numpy array
        b: numpy array

    Returns:
        float: cosine similarity in range [-1.0, 1.0]
    """
    a = np.asarray(a, dtype=np.float32).flatten()
    b = np.asarray(b, dtype=np.float32).flatten()

    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)

    if norm_a < 1e-10 or norm_b < 1e-10:
        return 0.0

    return float(np.dot(a, b) / (norm_a * norm_b))


# =================================================================
# FACE ALIGNMENT
# =================================================================

def align_face(image, landmarks, output_size=112):
    """
    Align a face image using 5 facial landmarks via affine transform.

    Uses the standard ArcFace alignment template (112x112).

    Args:
        image: BGR numpy array (the face crop or full image)
        landmarks: array-like of shape (5, 2) or flat (10,)
                   containing 5 facial landmarks:
                   [left_eye, right_eye, nose, left_mouth, right_mouth]
        output_size: output image size (default 112 for ArcFace)

    Returns:
        Aligned face image (output_size x output_size x 3) or None
        if alignment fails.
    """
    if image is None or image.size == 0:
        return None

    landmarks = np.asarray(landmarks, dtype=np.float32)

    # Handle flat landmark array [x1,y1,x2,y2,...,x5,y5]
    if landmarks.ndim == 1:
        if len(landmarks) != 10:
            return None
        landmarks = landmarks.reshape(5, 2)

    if landmarks.shape != (5, 2):
        return None

    # Scale reference landmarks to output size
    scale = output_size / 112.0
    ref = ARCFACE_REF_LANDMARKS * scale

    # Estimate affine transform
    # Use the first 3 landmark pairs (eyes + nose) for stability
    transform = cv2.getAffineTransform(
        landmarks[:3].astype(np.float32),
        ref[:3].astype(np.float32)
    )

    aligned = cv2.warpAffine(
        image,
        transform,
        (output_size, output_size),
        borderValue=(0, 0, 0)
    )

    return aligned


# =================================================================
# BOUNDING BOX VALIDATION
# =================================================================

def validate_bbox(x, y, w, h, img_w, img_h, min_size=30):
    """
    Validate a bounding box against image dimensions and minimum size.

    Args:
        x, y: top-left corner
        w, h: width and height
        img_w, img_h: image dimensions
        min_size: minimum acceptable face size in pixels

    Returns:
        bool: True if the bounding box is valid
    """
    if w <= 0 or h <= 0:
        return False

    if w < min_size or h < min_size:
        return False

    if x < 0 or y < 0:
        return False

    if x + w > img_w or y + h > img_h:
        return False

    return True


# =================================================================
# FACE QUALITY
# =================================================================

def estimate_blur(image):
    """
    Estimate image blur using Laplacian variance.

    Higher values = sharper image.

    Args:
        image: BGR or grayscale numpy array

    Returns:
        float: Laplacian variance (blur metric)
    """
    if image is None or image.size == 0:
        return 0.0

    if len(image.shape) == 3:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    else:
        gray = image

    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def check_brightness(image):
    """
    Check image brightness using mean pixel value.

    Args:
        image: BGR or grayscale numpy array

    Returns:
        float: mean brightness (0-255)
    """
    if image is None or image.size == 0:
        return 0.0

    if len(image.shape) == 3:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    else:
        gray = image

    return float(np.mean(gray))


def calculate_face_quality(
    image,
    bbox=None,
    confidence=0.0,
    landmarks=None,
    img_w=0,
    img_h=0
):
    """
    Calculate a composite face quality score.

    Combines multiple factors:
    - Detection confidence
    - Image sharpness (blur)
    - Brightness
    - Face size relative to image
    - Landmark validity

    Args:
        image: face crop (BGR numpy array)
        bbox: (x, y, w, h) tuple or None
        confidence: detection confidence [0, 1]
        landmarks: array of 5 facial landmarks or None
        img_w: full image width (for relative size)
        img_h: full image height (for relative size)

    Returns:
        float: quality score in range [0.0, 1.0]
    """
    if image is None or image.size == 0:
        return 0.0

    scores = []

    # 1. Detection confidence (weight: 0.3)
    scores.append(min(confidence, 1.0) * 0.3)

    # 2. Blur score (weight: 0.25)
    blur_val = estimate_blur(image)
    # Normalize: 100+ is sharp, <20 is very blurry
    blur_score = min(blur_val / 100.0, 1.0)
    scores.append(blur_score * 0.25)

    # 3. Brightness score (weight: 0.15)
    brightness = check_brightness(image)
    # Ideal range: 60-200
    if 60 <= brightness <= 200:
        bright_score = 1.0
    elif brightness < 60:
        bright_score = brightness / 60.0
    else:
        bright_score = max(0.0, 1.0 - (brightness - 200) / 55.0)
    scores.append(bright_score * 0.15)

    # 4. Face size score (weight: 0.15)
    if bbox is not None and img_w > 0 and img_h > 0:
        _, _, bw, bh = bbox
        face_area_ratio = (bw * bh) / (img_w * img_h)
        # Good if face is at least 2% of image
        size_score = min(face_area_ratio / 0.02, 1.0)
    else:
        # Use crop dimensions directly
        h, w = image.shape[:2]
        size_score = min(min(w, h) / 80.0, 1.0)
    scores.append(size_score * 0.15)

    # 5. Landmark validity (weight: 0.15)
    if landmarks is not None:
        lm = np.asarray(landmarks, dtype=np.float32)
        if lm.ndim == 1:
            lm = lm.reshape(-1, 2) if len(lm) == 10 else None

        if lm is not None and lm.shape == (5, 2):
            # Check landmarks are within image bounds
            h, w = image.shape[:2]
            valid = np.all(lm >= 0) and np.all(lm[:, 0] < w) and np.all(lm[:, 1] < h)
            landmark_score = 1.0 if valid else 0.3
        else:
            landmark_score = 0.0
    else:
        landmark_score = 0.0
    scores.append(landmark_score * 0.15)

    return sum(scores)
