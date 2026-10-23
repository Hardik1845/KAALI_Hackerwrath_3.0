"""
Heatmap and Visual Saliency Generator for Deepfake Forensics
Renders Grad-CAM / feature anomaly overlays directly onto detected faces.
"""

import cv2
import numpy as np
import base64
from typing import Tuple


class HeatmapGenerator:
    """
    Renders visual forensic heatmaps identifying tampered boundaries and anomalous patches.
    """

    def generate_heatmap(
        self,
        original_face_bgr: np.ndarray,
        feature_maps: np.ndarray = None,
        anomaly_intensity: float = 0.8
    ) -> Tuple[np.ndarray, str]:
        """
        Creates an overlay highlighting high-gradient and high-frequency anomaly zones.
        Returns:
            - blended_bgr: np.ndarray (OpenCV BGR image with colormap)
            - base64_png: str (Data URI ready for HTML/React rendering)
        """
        h, w = original_face_bgr.shape[:2]

        if feature_maps is not None and len(feature_maps.shape) == 3:
            # Average across feature channels
            cam = np.mean(feature_maps, axis=0)
            cam = np.maximum(cam, 0)
            cam = cv2.resize(cam, (w, h), interpolation=cv2.INTER_CUBIC)
            if np.max(cam) > 0:
                cam = cam / np.max(cam)
        else:
            # Fallback to high-frequency edge & texture gradient map
            gray = cv2.cvtColor(original_face_bgr, cv2.COLOR_BGR2GRAY)
            sobelx = cv2.Sobel(gray, cv2.CV_64F, 1, 0, ksize=3)
            sobely = cv2.Sobel(gray, cv2.CV_64F, 0, 1, ksize=3)
            grad_mag = np.sqrt(sobelx**2 + sobely**2)
            cam = cv2.GaussianBlur(grad_mag, (15, 15), 0)
            if np.max(cam) > 0:
                cam = cam / np.max(cam)

        # Apply threshold and scale by anomaly intensity
        cam = np.clip(cam * (anomaly_intensity / 100.0) * 1.5, 0.0, 1.0)
        
        # Colorize using Jet or Inferno colormap (Blue=cold, Red=suspicious)
        heatmap_uint8 = np.uint8(255 * cam)
        heatmap_color = cv2.applyColorMap(heatmap_uint8, cv2.COLORMAP_JET)

        # Blend with original face
        alpha = 0.45
        blended = cv2.addWeighted(heatmap_color, alpha, original_face_bgr, 1.0 - alpha, 0)

        # Draw suspicious boundary highlights if intensity is high
        if anomaly_intensity > 50.0:
            contours, _ = cv2.findContours(
                np.uint8(cam > 0.65 * np.max(cam) * 255), 
                cv2.RETR_EXTERNAL, 
                cv2.CHAIN_APPROX_SIMPLE
            )
            cv2.drawContours(blended, contours, -1, (0, 0, 255), 2)

        # Encode to Base64 PNG for Web API
        _, buffer = cv2.imencode(".png", blended)
        base64_str = base64.b64encode(buffer).decode("utf-8")
        base64_uri = f"data:image/png;base64,{base64_str}"

        return blended, base64_uri
