"""
MesoNet Architecture & Spatial Artifact Detection
Reference: "MesoNet: a Compact Facial Video Forgery Detection Network" (Afchar et al., IEEE WIFS 2018)
"""

import os
import torch
import torch.nn as nn
import numpy as np
import cv2
from typing import Dict, Any, Tuple


class Meso4(nn.Module):
    """
    Compact 4-layer CNN designed for facial video and image forgery detection.
    Very fast CPU inference (<15ms per face) with zero GPU requirement.
    """

    def __init__(self, num_classes: int = 1):
        super(Meso4, self).__init__()
        
        self.conv1 = nn.Conv2d(3, 8, 3, padding=1, bias=True)
        self.bn1 = nn.BatchNorm2d(8)
        self.relu = nn.ReLU(inplace=True)
        self.leaky = nn.LeakyReLU(0.1)
        self.maxpool1 = nn.MaxPool2d(kernel_size=2, stride=2)

        self.conv2 = nn.Conv2d(8, 8, 5, padding=2, bias=True)
        self.bn2 = nn.BatchNorm2d(8)
        self.maxpool2 = nn.MaxPool2d(kernel_size=2, stride=2)

        self.conv3 = nn.Conv2d(8, 16, 5, padding=2, bias=True)
        self.bn3 = nn.BatchNorm2d(16)
        self.maxpool3 = nn.MaxPool2d(kernel_size=2, stride=2)

        self.conv4 = nn.Conv2d(16, 16, 5, padding=2, bias=True)
        self.bn4 = nn.BatchNorm2d(16)
        self.maxpool4 = nn.MaxPool2d(kernel_size=4, stride=4)

        self.dropout = nn.Dropout(0.5)
        # 256x256 -> pool(2)->128 -> pool(2)->64 -> pool(2)->32 -> pool(4)->8 => 16 * 8 * 8 = 1024
        self.fc1 = nn.Linear(16 * 8 * 8, 16)
        self.fc2 = nn.Linear(16, num_classes)
        self.sigmoid = nn.Sigmoid()

    def forward(self, x: torch.Tensor) -> Tuple[torch.Tensor, torch.Tensor]:
        x = self.conv1(x)
        x = self.relu(x)
        x = self.bn1(x)
        x = self.maxpool1(x)

        x = self.conv2(x)
        x = self.relu(x)
        x = self.bn2(x)
        x = self.maxpool2(x)

        x = self.conv3(x)
        x = self.relu(x)
        x = self.bn3(x)
        features = self.maxpool3(x)  # Activation map for anomaly heatmap

        x = self.conv4(features)
        x = self.relu(x)
        x = self.bn4(x)
        x = self.maxpool4(x)

        x = self.dropout(x)
        # Permute from PyTorch (N, C, H, W) to Keras (N, H, W, C) layout before flattening
        x = x.permute(0, 2, 3, 1).contiguous().view(x.size(0), -1)
        x = self.fc1(x)
        x = self.leaky(x)
        x = self.dropout(x)
        x = self.fc2(x)
        prob = self.sigmoid(x)

        return prob, features


class SpatialArtifactDetector:
    """
    Evaluates spatial pixel anomalies, boundary blending, and facial landmark inconsistencies.
    Works in tandem with MesoNet to capture face-swap boundary seams.
    """

    def __init__(self, weights_path: str = None):
        self.model = Meso4()
        
        # Auto-load official FaceForensics pretrained weights if available
        if weights_path is None:
            default_weights = os.path.join(os.path.dirname(__file__), "weights", "meso4_df.pth")
            if os.path.exists(default_weights):
                weights_path = default_weights

        self.has_pretrained = False
        if weights_path and os.path.exists(weights_path):
            try:
                state_dict = torch.load(weights_path, map_location="cpu", weights_only=True)
                self.model.load_state_dict(state_dict)
                self.has_pretrained = True
            except Exception as e:
                print(f"[!] Warning: Could not load MesoNet weights from {weights_path}: {e}")

        if not self.has_pretrained:
            raise RuntimeError("Pretrained MesoNet weights could not be loaded; refusing to score with random weights.")
        self.model.eval()

    def detect_boundary_blending_artifacts(self, face_bgr: np.ndarray) -> float:
        """
        Calculates Face X-Ray style boundary seam and noise inconsistency.
        Face swaps exhibit boundary softening and mismatched sensor noise
        between inserted face and surrounding background.
        """
        gray = cv2.cvtColor(face_bgr, cv2.COLOR_BGR2GRAY)
        h, w = gray.shape

        # 1. High-frequency noise residue (sensor PRNU estimation)
        denoised = cv2.GaussianBlur(gray, (5, 5), 0)
        noise_residue = cv2.absdiff(gray, denoised)

        # Inner face mask (center 50%) vs Outer boundary mask
        inner_mask = np.zeros((h, w), dtype=np.uint8)
        cx, cy = w // 2, h // 2
        rx, ry = int(w * 0.28), int(h * 0.32)
        cv2.ellipse(inner_mask, (cx, cy), (rx, ry), 0, 0, 360, 255, -1)
        outer_mask = cv2.bitwise_not(inner_mask)

        inner_noise_std = float(np.std(noise_residue[inner_mask == 255]))
        outer_noise_std = float(np.std(noise_residue[outer_mask == 255]))

        # Noise discrepancy ratio
        noise_diff = abs(inner_noise_std - outer_noise_std) / (inner_noise_std + 1e-5)

        # 2. Laplacian edge gradient discontinuity along perimeter ring
        laplacian = cv2.Laplacian(gray, cv2.CV_64F)
        ring_mask = np.zeros((h, w), dtype=np.uint8)
        cv2.ellipse(ring_mask, (cx, cy), (int(rx * 1.25), int(ry * 1.25)), 0, 0, 360, 255, -1)
        ring_mask = cv2.subtract(ring_mask, inner_mask)

        ring_gradient_var = float(np.var(laplacian[ring_mask == 255]))
        inner_gradient_var = float(np.var(laplacian[inner_mask == 255]))

        edge_ratio = abs(inner_gradient_var - ring_gradient_var) / (inner_gradient_var + 1e-5)

        # Combined artifact metric
        artifact_score = min(100.0, max(0.0, (noise_diff * 45.0) + (edge_ratio * 35.0)))
        return float(artifact_score)

    def analyze_face(self, face_bgr: np.ndarray) -> Dict[str, Any]:
        """
        Runs neural spatial inference + boundary blending analysis.
        """
        # Preprocess for Meso4: normalized to [-1, 1], resized to 256x256
        face_resized = cv2.resize(face_bgr, (256, 256), interpolation=cv2.INTER_AREA)
        face_rgb = cv2.cvtColor(face_resized, cv2.COLOR_BGR2RGB)
        tensor_in = torch.from_numpy(face_rgb).permute(2, 0, 1).unsqueeze(0).float() / 255.0
        # Official MesoNet input scaling is [0, 1]
        
        with torch.no_grad():
            prob, feature_maps = self.model(tensor_in)
            real_prob = float(prob.item())
            # In MesoNet official weights: 1.0 = Real, 0.0 = Deepfake
            if self.has_pretrained:
                meso_fake_score = float((1.0 - real_prob) * 100.0)
            else:
                meso_fake_score = float(real_prob * 100.0)

        blending_score = self.detect_boundary_blending_artifacts(face_resized)

        # Composite spatial score driven by pretrained MesoNet-4
        if self.has_pretrained:
            if meso_fake_score >= 50.0:
                spatial_score = max(meso_fake_score, blending_score)
            else:
                spatial_score = 0.85 * meso_fake_score + 0.15 * min(blending_score, 30.0)
        else:
            spatial_score = 0.65 * meso_fake_score + 0.35 * blending_score

        spatial_score = float(np.clip(spatial_score, 1.0, 99.0))

        return {
            "spatial_score": round(spatial_score, 1),
            "meso_activation": round(meso_fake_score, 1),
            "boundary_blending_score": round(blending_score, 1),
            "pretrained_weights_active": self.has_pretrained,
            "feature_maps": feature_maps.squeeze(0).cpu().numpy(),
        }
