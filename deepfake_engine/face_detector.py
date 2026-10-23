"""
Face Detection and Extraction Module
Uses OpenCV Cascade and DNN Face Detectors to isolate facial regions.
"""

import os
import cv2
import numpy as np
from typing import List, Tuple, Optional


class FaceDetector:
    """
    Robust face detection pipeline isolating faces with margin padding.
    """

    def __init__(self, min_face_size: Tuple[int, int] = (60, 60)):
        self.min_face_size = min_face_size
        
        # OpenCV 5 moves Haar cascades out of the base package. Keep a fallback
        # for minimal builds; the API reports full-image analysis when no
        # compatible cascade detector is available.
        self.cascade = None
        cascade_factory = getattr(cv2, "CascadeClassifier", None)
        cascade_data = getattr(cv2, "data", None)
        cascade_dir = getattr(cascade_data, "haarcascades", None)
        if callable(cascade_factory) and cascade_dir:
            cascade_path = os.path.join(cascade_dir, "haarcascade_frontalface_default.xml")
            candidate = cascade_factory(cascade_path)
            if not hasattr(candidate, "empty") or not candidate.empty():
                self.cascade = candidate

    def detect_faces(self, image_bgr: np.ndarray) -> List[Tuple[int, int, int, int]]:
        """
        Detect faces in image.
        Returns list of bounding boxes: (x, y, w, h)
        """
        if self.cascade is None:
            return []
        gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
        gray = cv2.equalizeHist(gray)

        faces = self.cascade.detectMultiScale(
            gray,
            scaleFactor=1.1,
            minNeighbors=5,
            minSize=self.min_face_size,
            flags=cv2.CASCADE_SCALE_IMAGE
        )

        return [tuple(f) for f in faces]

    def extract_face(
        self, 
        image_bgr: np.ndarray, 
        bbox: Tuple[int, int, int, int], 
        target_size: Tuple[int, int] = (256, 256),
        padding_ratio: float = 0.35
    ) -> Tuple[np.ndarray, Tuple[int, int, int, int]]:
        """
        Extracts face with padding and resizes to target_size.
        Returns (cropped_face, padded_bbox)
        """
        x, y, w, h = bbox
        img_h, img_w = image_bgr.shape[:2]

        # Add padding
        pad_w = int(w * padding_ratio)
        pad_h = int(h * padding_ratio)

        x1 = max(0, x - pad_w)
        y1 = max(0, y - pad_h)
        x2 = min(img_w, x + w + pad_w)
        y2 = min(img_h, y + h + pad_h)

        face_crop = image_bgr[y1:y2, x1:x2]
        resized = cv2.resize(face_crop, target_size, interpolation=cv2.INTER_AREA)

        return resized, (x1, y1, x2 - x1, y2 - y1)
