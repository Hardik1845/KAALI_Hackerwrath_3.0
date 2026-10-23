"""
Unified Deepfake & Morph Detection Pipeline
Fuses Spatial Artifacts (MesoNet) + Spectral Frequency Decomposition (DCT/FFT).
"""

import os
import cv2
import numpy as np
from typing import Dict, Any, List, Optional, Union
from dataclasses import dataclass, asdict

from .face_detector import FaceDetector
from .spatial_detector import SpatialArtifactDetector
from .spectral_analyzer import SpectralAnalyzer
from .heatmap_generator import HeatmapGenerator


@dataclass
class DetectionResult:
    is_deepfake: bool
    verdict: str  # "AUTHENTIC" | "SUSPICIOUS" | "LIKELY_DEEPFAKE" | "CONFIRMED_DEEPFAKE"
    manipulation_probability: float  # [0.0, 1.0]
    authenticity_score: float  # [0, 100] (higher = more authentic)
    manipulation_score: float  # [0, 100] (higher = more fake)
    manipulation_type: str
    spatial_score: float
    frequency_score: float
    ela_score: float
    faces_detected: int
    bounding_box: Optional[List[int]]  # [x, y, w, h]
    heatmap_base64: Optional[str]
    forensic_notes: str
    faces_details: Optional[List[Dict[str, Any]]] = None


class DeepfakeDetector:
    """
    End-to-end forensic deepfake and morphed image detector.
    Analyzes all detected faces to prevent adversarial secondary face insertion.
    """

    def __init__(self):
        self.face_detector = FaceDetector()
        self.spatial_detector = SpatialArtifactDetector()
        self.spectral_analyzer = SpectralAnalyzer()
        self.heatmap_generator = HeatmapGenerator()

    def _compute_ela_metric(self, crop_bgr: np.ndarray) -> float:
        """
        Error Level Analysis (ELA): Computes JPEG re-compression discrepancy.
        Morphed, retouched, and AI-inpainted patches exhibit distinct error rates.
        """
        try:
            _, enc = cv2.imencode('.jpg', crop_bgr, [cv2.IMWRITE_JPEG_QUALITY, 90])
            resaved = cv2.imdecode(enc, cv2.IMREAD_COLOR)
            diff = cv2.absdiff(crop_bgr, resaved).astype(np.float32)
            max_err = float(np.max(diff))
            mean_err = float(np.mean(diff))
            # Normal camera photos at Q90 have max diff < 28 and mean < 1.5
            # Morphs and high-contrast splices spike max diff above 40
            ela_score = min(100.0, max(0.0, (max_err - 20.0) * 2.2 + mean_err * 8.0))
            return round(ela_score, 1)
        except Exception:
            return 0.0

    def analyze_image(
        self, 
        image_input: Union[str, np.ndarray, bytes],
        generate_visual_heatmap: bool = True
    ) -> DetectionResult:
        """
        Runs multi-face dual-stream forensic inspection on an image.
        """
        # 1. Load image
        if isinstance(image_input, str):
            if not os.path.exists(image_input):
                raise FileNotFoundError(f"Input image not found: {image_input}")
            img_bgr = cv2.imread(image_input)
            if img_bgr is None:
                raise ValueError(f"Failed to decode image from path: {image_input}")
        elif isinstance(image_input, bytes):
            nparr = np.frombuffer(image_input, np.uint8)
            img_bgr = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            if img_bgr is None:
                raise ValueError("Failed to decode image bytes")
        elif isinstance(image_input, np.ndarray):
            img_bgr = image_input
        else:
            raise TypeError("Unsupported image_input type")

        # 2. Detect faces
        faces = self.face_detector.detect_faces(img_bgr)
        faces_count = len(faces)

        face_candidates = []
        if faces:
            for idx, box in enumerate(faces):
                face_crop, padded_box = self.face_detector.extract_face(
                    img_bgr, box, target_size=(256, 256)
                )
                face_candidates.append({
                    "index": idx,
                    "crop": face_crop,
                    "box": padded_box,
                    "raw_box": box
                })
        else:
            # Fallback to whole image if no face detected
            face_crop = cv2.resize(img_bgr, (256, 256), interpolation=cv2.INTER_AREA)
            padded_box = [0, 0, img_bgr.shape[1], img_bgr.shape[0]]
            face_candidates.append({
                "index": 0,
                "crop": face_crop,
                "box": padded_box,
                "raw_box": padded_box
            })

        # 3. Analyze each face candidate
        analyzed_faces = []
        for cand in face_candidates:
            fcrop = cand["crop"]
            # Spatial Stream: MesoNet-4 + Face X-Ray boundary seams
            spatial_res = self.spatial_detector.analyze_face(fcrop)
            s_score = spatial_res["spatial_score"]
            f_maps = spatial_res["feature_maps"]

            # Frequency Stream: 2D DCT + Azimuthal FFT
            spectral_res = self.spectral_analyzer.analyze_image(fcrop)
            freq_score = spectral_res["frequency_score"]

            # ELA Compression Stream
            ela_score = self._compute_ela_metric(fcrop)

            # Composite Score for this face
            max_stream = max(s_score, freq_score, ela_score)
            if max_stream >= 50.0:
                comp = max_stream * 0.75 + s_score * 0.15 + freq_score * 0.10
            else:
                comp = 0.55 * s_score + 0.30 * freq_score + 0.15 * ela_score

            comp = float(np.clip(comp, 0.0, 100.0))

            analyzed_faces.append({
                "index": cand["index"],
                "box": cand["box"],
                "crop": fcrop,
                "feature_maps": f_maps,
                "spatial_score": s_score,
                "frequency_score": freq_score,
                "ela_score": ela_score,
                "composite_score": comp,
                "spectral_res": spectral_res,
                "spatial_res": spatial_res
            })

        # 4. Select Primary Culprit (highest risk face)
        # Any tampered face in a multi-subject photo constitutes an attack/violation
        analyzed_faces.sort(key=lambda x: x["composite_score"], reverse=True)
        primary = analyzed_faces[0]

        composite_score = primary["composite_score"]
        spatial_score = primary["spatial_score"]
        frequency_score = primary["frequency_score"]
        ela_score = primary["ela_score"]
        padded_box = primary["box"]
        feature_maps = primary["feature_maps"]
        spectral_res = primary["spectral_res"]

        manipulation_prob = round(composite_score / 100.0, 4)
        authenticity_score = round(100.0 - composite_score, 1)

        # 5. Classification & Verdict
        if composite_score >= 75.0:
            verdict = "CONFIRMED_DEEPFAKE"
            is_fake = True
            manipulation_type = (
                "GAN Face-Swap / Deepfake"
                if spatial_score > frequency_score
                else "Diffusion / Synthetic Generation"
            )
            notes = (
                f"Severe manipulation detected on face #{primary['index'] + 1} of {faces_count}. "
                f"High spatial blending anomalies ({spatial_score}%) with spectral distortion ({frequency_score}%)."
            )
        elif composite_score >= 55.0:
            verdict = "LIKELY_DEEPFAKE"
            is_fake = True
            manipulation_type = "Facial Morphing / Retouching"
            notes = (
                f"Suspicious facial alterations found on face #{primary['index'] + 1}. Unnatural spectral decay "
                f"(slope: {spectral_res['spectral_decay_slope']}) indicates artificial tampering."
            )
        elif composite_score >= 35.0:
            verdict = "SUSPICIOUS"
            is_fake = False
            manipulation_type = "Possible Compression / Minor Retouch"
            notes = (
                "Borderline artifact thresholds detected. May be due to heavy JPEG "
                "re-compression or minor beauty filter smoothing."
            )
        else:
            verdict = "AUTHENTIC"
            is_fake = False
            manipulation_type = "Authentic Camera Capture"
            notes = (
                "Natural photo characteristics. Smooth continuous 1/f spectral decay "
                "with coherent pixel boundary variance."
            )

        # 6. Generate Visual Heatmap Overlay for Primary Culprit
        heatmap_base64 = None
        if generate_visual_heatmap:
            _, heatmap_base64 = self.heatmap_generator.generate_heatmap(
                primary["crop"],
                feature_maps=feature_maps,
                anomaly_intensity=composite_score
            )

        faces_details = [
            {
                "face_index": int(f["index"] + 1),
                "box": [int(v) for v in f["box"]],
                "manipulation_score": float(round(f["composite_score"], 1)),
                "spatial_score": float(round(f["spatial_score"], 1)),
                "frequency_score": float(round(f["frequency_score"], 1)),
                "ela_score": float(round(f["ela_score"], 1)),
            }
            for f in analyzed_faces
        ]

        return DetectionResult(
            is_deepfake=is_fake,
            verdict=verdict,
            manipulation_probability=manipulation_prob,
            authenticity_score=authenticity_score,
            manipulation_score=round(composite_score, 1),
            manipulation_type=manipulation_type,
            spatial_score=spatial_score,
            frequency_score=frequency_score,
            ela_score=ela_score,
            faces_detected=int(faces_count),
            bounding_box=[int(v) for v in padded_box],
            heatmap_base64=heatmap_base64,
            forensic_notes=notes,
            faces_details=faces_details,
        )
