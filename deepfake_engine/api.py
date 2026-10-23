from contextlib import asynccontextmanager
from dataclasses import asdict
from io import BytesIO
import logging
import os

# Keep numerical libraries from starting large, competing thread pools on CPU.
# These must be set before importing PyTorch, NumPy, SciPy, or OpenCV.
os.environ["OMP_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"
os.environ["OPENBLAS_NUM_THREADS"] = "1"
# Anaconda's MKL can load another Intel OpenMP runtime alongside PyTorch.
# Sequential MKL avoids that duplicate runtime while retaining CPU inference.
os.environ["MKL_THREADING_LAYER"] = "SEQUENTIAL"

import cv2
import numpy as np
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from PIL import Image, UnidentifiedImageError
from starlette.formparsers import MultiPartParser

from .pipeline import DeepfakeDetector

try:
    import torch
    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)
except (ImportError, RuntimeError):
    pass
if hasattr(cv2, "setNumThreads"):
    cv2.setNumThreads(1)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("kaali.deepfake")
MAX_IMAGE_BYTES = 15 * 1024 * 1024
MAX_IMAGE_PIXELS = 25_000_000
# Keep accepted uploads in memory instead of Starlette's default small disk-spool threshold.
MultiPartParser.spool_max_size = MAX_IMAGE_BYTES + 1024 * 1024
_detector: DeepfakeDetector | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _detector
    # Loading fails closed when the local pretrained checkpoint is missing or invalid.
    _detector = DeepfakeDetector()
    if not _detector.spatial_detector.has_pretrained:
        raise RuntimeError("Pretrained MesoNet weights are required.")
    logger.info("DeepDefend ready; inference device=CPU; pretrained=True")
    yield
    _detector = None


app = FastAPI(title="Kaali DeepDefend", version="1.0.0", lifespan=lifespan)


@app.get("/health")
def health():
    ready = _detector is not None
    face_detection = bool(ready and _detector.face_detector.cascade is not None)
    pretrained = bool(ready and _detector.spatial_detector.has_pretrained)
    return {"ok": ready and pretrained, "service": "Kaali DeepDefend", "device": "CPU", "pretrained_weights": pretrained,
            "face_detection": "haar_cascade" if face_detection else "full_image_fallback",
            "external_model_api": False}


@app.post("/api/v1/detect/deepfake")
async def detect_deepfake(image: UploadFile = File(...)):
    if _detector is None:
        raise HTTPException(status_code=503, detail="DeepDefend is not ready.")
    allowed = {"image/jpeg", "image/png", "image/webp", "image/bmp"}
    if (image.content_type or "").lower() not in allowed:
        raise HTTPException(status_code=415, detail="Use a JPEG, PNG, WebP, or BMP image.")
    content = await image.read(MAX_IMAGE_BYTES + 1)
    if not content:
        raise HTTPException(status_code=400, detail="The uploaded image is empty.")
    if len(content) > MAX_IMAGE_BYTES:
        raise HTTPException(status_code=413, detail="Image upload is too large (15 MB maximum).")
    try:
        with Image.open(BytesIO(content)) as decoded:
            if decoded.format not in {"JPEG", "PNG", "WEBP", "BMP"}:
                raise HTTPException(status_code=415, detail="The image contents do not match a supported format.")
            if decoded.width * decoded.height > MAX_IMAGE_PIXELS:
                raise HTTPException(status_code=413, detail="Image dimensions are too large (25 megapixels maximum).")
            decoded.verify()
    except HTTPException:
        raise
    except (UnidentifiedImageError, OSError, ValueError):
        raise HTTPException(status_code=400, detail="The uploaded file is not a valid image.")
    result = await run_in_threadpool(_detector.analyze_image, content, True)
    payload = asdict(result)
    # These are heuristic artifact scores, not calibrated probabilities.
    payload["score_notice"] = "Scores are uncalibrated signals from heuristic and pretrained analysis, not proof of authenticity or manipulation."
    payload["ela_score"] = float(result.ela_score)
    payload["analysis_scope"] = "Detected faces; full-image fallback when face detection is unavailable or no face is detected."
    return payload
