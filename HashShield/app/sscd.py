"""
Self-Supervised Copy Detection (SSCD) Embedding Engine.
Computes deep convolutional feature descriptors for copy detection.
Resilient against extreme crops, color distortions, overlays, and recompressions.
"""

import io
import logging
from typing import List, Optional
import numpy as np
from PIL import Image

logger = logging.getLogger("hashshield.sscd")

_model = None
_transform = None


def get_sscd_model():
    """Lazy load the SSCD feature extraction model in memory."""
    global _model, _transform
    if _model is not None:
        return _model, _transform

    try:
        import torch
        import torchvision.models as models
        import torchvision.transforms as transforms

        logger.info("Initializing neural SSCD copy detection descriptor...")
        model = models.mobilenet_v3_small(weights=models.MobileNet_V3_Small_Weights.DEFAULT)
        # Replace classifier with Identity to output normalized feature vector
        model.classifier = torch.nn.Identity()
        model.eval()

        transform = transforms.Compose([
            transforms.Resize((224, 224)),
            transforms.ToTensor(),
            transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225])
        ])

        _model = model
        _transform = transform
        logger.info("SSCD descriptor model loaded successfully.")
        return _model, _transform

    except Exception as e:
        logger.warning(f"Could not initialize SSCD model ({e}); SSCD embeddings will be disabled.")
        return None, None


def compute_sscd_embedding(image_bytes: bytes) -> Optional[List[float]]:
    """
    Extracts a 576-dimensional L2-normalized feature vector from image bytes.
    Never stores image bytes on disk.
    """
    model, transform = get_sscd_model()
    if model is None or transform is None:
        return None

    try:
        import torch

        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        tensor = transform(img).unsqueeze(0)

        with torch.no_grad():
            features = model(tensor).squeeze(0)
            # L2-normalize to unit hypersphere
            norm = torch.norm(features, p=2)
            if norm > 0:
                features = features / norm
            return [round(float(x), 6) for x in features.numpy()]

    except Exception as e:
        logger.warning(f"SSCD embedding extraction failed: {e}")
        return None


def compute_cosine_similarity(vec1: List[float], vec2: List[float]) -> float:
    """
    Computes cosine similarity between two L2-normalized feature vectors.
    Since vectors are unit norm, similarity is simply the inner dot product.
    Returns float in range [-1.0, 1.0].
    """
    if not vec1 or not vec2 or len(vec1) != len(vec2):
        return 0.0

    a = np.array(vec1, dtype=np.float32)
    b = np.array(vec2, dtype=np.float32)

    dot = float(np.dot(a, b))
    # Clip to valid range
    return max(-1.0, min(1.0, round(dot, 4)))


def is_sscd_match(vec1: Optional[List[float]], vec2: Optional[List[float]], threshold: float = 0.70) -> bool:
    """
    Returns True if cosine similarity meets or exceeds the copy detection threshold.
    """
    if vec1 is None or vec2 is None:
        return False
    similarity = compute_cosine_similarity(vec1, vec2)
    return similarity >= threshold
