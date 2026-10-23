"""
Frequency-Domain Spectral Analyzer for Deepfake & GAN Artifact Detection
Based on: "Leveraging Frequency Analysis for Deep Fake Image Recognition" (Frank et al., ICML 2020)
"""

import numpy as np
import scipy.fftpack as fft
import cv2
from typing import Dict, Any, Tuple


class SpectralAnalyzer:
    """
    Analyzes spatial frequency distributions to detect GAN upsampling artifacts.
    All modern GANs and diffusion pipelines introduce periodic spectral peaks
    during transposed convolutions and bilinear/bicubic resizing.
    """

    def __init__(self, block_size: int = 64):
        self.block_size = block_size

    def compute_dct_spectrum(self, gray_face: np.ndarray) -> np.ndarray:
        """
        Computes 2D Discrete Cosine Transform (DCT-II, ortho normalized) of face.
        """
        img_float = gray_face.astype(np.float32) / 255.0
        # 2D DCT
        dct_2d = fft.dctn(img_float, norm="ortho")
        return dct_2d

    def compute_radial_profile(self, power_spectrum: np.ndarray) -> np.ndarray:
        """
        Computes radially averaged power spectrum (azimuthal average).
        Authentic camera images decay smoothly as 1/f^alpha (natural image statistics).
        Deepfakes show anomalous high-frequency ripples and energy spikes.
        """
        h, w = power_spectrum.shape
        center_y, center_x = h // 2, w // 2
        
        y, x = np.indices((h, w))
        r = np.sqrt((x - center_x) ** 2 + (y - center_y) ** 2).astype(np.int32)
        
        max_r = int(min(center_x, center_y))
        radial_profile = np.zeros(max_r)
        
        for radius in range(max_r):
            mask = (r == radius)
            if np.any(mask):
                radial_profile[radius] = np.mean(power_spectrum[mask])
                
        return radial_profile

    def analyze_image(self, face_bgr: np.ndarray) -> Dict[str, Any]:
        """
        Executes spectral decomposition and anomaly scoring.
        Returns:
            - frequency_score: [0, 100] (higher = more anomalous/deepfake)
            - high_freq_energy_ratio
            - spectral_decay_slope
            - is_synthetic_frequency
        """
        if len(face_bgr.shape) == 3:
            gray = cv2.cvtColor(face_bgr, cv2.COLOR_BGR2GRAY)
        else:
            gray = face_bgr

        # Resize to standard 256x256 for consistent spectral statistics
        gray_256 = cv2.resize(gray, (256, 256), interpolation=cv2.INTER_AREA)

        # 1. 2D FFT shifted power spectrum. Keep values nonnegative so the
        # later log-log radial fit remains defined for blank/low-detail images.
        f = np.fft.fft2(gray_256)
        fshift = np.fft.fftshift(f)
        power_spectrum = np.abs(fshift) ** 2

        # 2. 2D DCT Analysis
        dct_coeffs = self.compute_dct_spectrum(gray_256)
        abs_dct = np.abs(dct_coeffs)

        # High-frequency quadrant energy ratio
        h, w = abs_dct.shape
        half_h, half_w = h // 2, w // 2
        
        low_freq_energy = np.sum(abs_dct[:half_h, :half_w]) + 1e-8
        high_freq_energy = np.sum(abs_dct[half_h:, half_w:])
        hf_ratio = float(high_freq_energy / (low_freq_energy + high_freq_energy))

        # 3. High-Frequency Grid Regularity / Variance Check
        # GAN upsamplers cause regular periodic peaks in the upper frequencies
        hf_patch = abs_dct[half_h:, half_w:]
        spectral_kurtosis = float(np.mean(((hf_patch - np.mean(hf_patch)) / (np.std(hf_patch) + 1e-8)) ** 4))

        # 4. Radially averaged power spectrum decay
        radial_profile = self.compute_radial_profile(power_spectrum)
        if len(radial_profile) > 10:
            radii = np.arange(1, len(radial_profile), dtype=np.float64)
            x_vals = np.log(radii)
            y_vals = np.log(np.maximum(radial_profile[1:], 1e-12))
            # Natural images have linear negative slope in log-log power spectrum
            slope, _ = np.polyfit(x_vals, y_vals, 1)
            if not np.isfinite(slope):
                slope = -1.5
        else:
            slope = -1.5

        # Normal human photos have slope around -1.8 to -2.3 and hf_ratio around 0.08 - 0.16
        # GAN deepfakes have flatter slopes (-0.8 to -1.3) and higher kurtosis/ratio
        anomaly_metric = 0.0
        
        # Anomaly scoring heuristics derived from FaceForensics++ spectral benchmarks
        if slope > -1.4:  # Flat slope = synthetic upsampling
            anomaly_metric += min(40.0, (slope - (-1.4)) * 50.0 + 20.0)
            
        if hf_ratio > 0.18:
            anomaly_metric += min(35.0, (hf_ratio - 0.18) * 200.0)

        if spectral_kurtosis > 15.0 or spectral_kurtosis < 3.0:
            anomaly_metric += min(25.0, abs(spectral_kurtosis - 9.0) * 1.5)

        freq_score = float(np.clip(anomaly_metric, 5.0, 98.0))

        return {
            "frequency_score": round(freq_score, 1),
            "high_freq_energy_ratio": round(hf_ratio, 4),
            "spectral_decay_slope": round(float(slope), 3),
            "spectral_kurtosis": round(spectral_kurtosis, 2),
            "is_synthetic_frequency": freq_score > 55.0,
        }
