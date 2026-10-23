"""
AURA Pose Estimator — YOLO11n-pose

Extracts human body keypoints from a target ROI using YOLO11n-pose.
This is the ONLY behavior-related DL model.  All behavior classification,
fall detection, and state transitions use deterministic geometry.

Optimization:
  - Crops the target bounding box + padding instead of running on the
    full camera image.
  - Configurable input resolution (default 320, benchmark 416 if needed).
  - Model loaded once in __init__, never inside callbacks.
"""

import os
from pathlib import Path

import numpy as np
import cv2
import torch

from ultralytics import YOLO


def resolve_model_path(model_path):
    """Resolve a pose model path from either an absolute path, a relative path,
    or the workspace root. This avoids launching in the wrong working directory
    and gives a clear error if the model file is missing or corrupted.
    """
    if not model_path:
        raise ValueError("Pose model path is empty")

    candidate = str(model_path)
    if os.path.isabs(candidate) and os.path.isfile(candidate):
        return candidate

    search_roots = [
        os.getcwd(),
        os.path.expanduser("~/AURA_WS3"),
        os.path.expanduser("~"),
        os.path.dirname(os.path.abspath(__file__)),
    ]

    for root in search_roots:
        if not root:
            continue
        for test_path in [
            os.path.abspath(os.path.join(root, candidate)),
            os.path.abspath(os.path.join(root, os.path.basename(candidate))),
        ]:
            if os.path.isfile(test_path):
                return test_path

    # Also walk parent directories from this file to find the repo root.
    current = Path(__file__).resolve().parent
    for parent in [current, *current.parents]:
        test_path = parent / candidate
        if test_path.is_file():
            return str(test_path)

    raise FileNotFoundError(
        f"Pose model '{model_path}' not found. "
        "Use an absolute path or ensure the model file exists in the workspace."
    )


class PoseEstimator:
    """YOLO11n-pose wrapper with target-ROI cropping."""

    def __init__(self, model_path='yolo11n-pose.pt', device='cpu',
                 imgsz=320, conf_thresh=0.5, roi_padding=0.15):
        self.imgsz = imgsz
        self.conf_thresh = conf_thresh
        self.roi_padding = roi_padding

        resolved_path = resolve_model_path(model_path)
        try:
            # Load model ONCE at startup
            self.model = YOLO(resolved_path)
        except Exception as exc:
            raise RuntimeError(
                f"Unable to load pose model '{resolved_path}'. "
                "The model file may be missing, truncated, or incompatible with this PyTorch/Ultralytics installation."
            ) from exc
        self.device = device

    def estimate_pose(self, frame, target_bbox):
        """
        Estimate pose keypoints inside the target bounding box.

        Args:
            frame: Full camera frame (BGR, np.ndarray).
            target_bbox: [x1, y1, x2, y2] from /follow/target.

        Returns:
            np.ndarray shape (17, 3) — [x, y, conf] per YOLO keypoint,
            or None if no pose detected.
        """
        if target_bbox is None:
            return None

        x1, y1, x2, y2 = [int(v) for v in target_bbox]
        h, w = frame.shape[:2]

        # --- Add padding around the target bbox ---
        bw = x2 - x1
        bh = y2 - y1
        pad_x = int(bw * self.roi_padding)
        pad_y = int(bh * self.roi_padding)

        rx1 = max(0, x1 - pad_x)
        ry1 = max(0, y1 - pad_y)
        rx2 = min(w, x2 + pad_x)
        ry2 = min(h, y2 + pad_y)

        if rx2 - rx1 < 30 or ry2 - ry1 < 30:
            return None

        # --- Crop target ROI ---
        crop = frame[ry1:ry2, rx1:rx2]

        # --- Run YOLO11n-pose on the cropped ROI ---
        results = self.model(
            crop,
            imgsz=self.imgsz,
            conf=self.conf_thresh,
            device=self.device,
            verbose=False,
        )

        if (not results or len(results) == 0
                or results[0].keypoints is None
                or results[0].keypoints.data is None
                or len(results[0].keypoints.data) == 0):
            return None

        # Take the first detected person's keypoints
        kps = results[0].keypoints.data[0].cpu().numpy()  # shape (17, 3)

        # --- Map crop-local coordinates back to full-frame coordinates ---
        keypoints = np.zeros((17, 3), dtype=np.float32)
        for i in range(17):
            keypoints[i][0] = kps[i][0] + rx1  # x
            keypoints[i][1] = kps[i][1] + ry1  # y
            keypoints[i][2] = kps[i][2]         # confidence

        return keypoints
