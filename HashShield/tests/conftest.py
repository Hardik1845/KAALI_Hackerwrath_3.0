import pytest
import io
from PIL import Image, ImageDraw
from fastapi.testclient import TestClient
from app.main import app
from app.config import settings
from app.storage import storage


@pytest.fixture(autouse=True)
def reset_storage(monkeypatch):
    """Clear in-memory storage and ensure mock provider during tests."""
    monkeypatch.setattr(settings, "DISCOVER_PROVIDER", "mock")
    if hasattr(storage, "vault"):
        storage.vault.clear()
        storage.cases.clear()
    yield
    if hasattr(storage, "vault"):
        storage.vault.clear()
        storage.cases.clear()


@pytest.fixture
def client():
    """TestClient with pre-configured secret API key."""
    return TestClient(app, headers={"X-API-Key": settings.API_KEY})


@pytest.fixture
def sample_image_bytes():
    """Generate a clean synthetic JPEG image in memory."""
    img = Image.new("RGB", (200, 200), color=(70, 130, 180))
    draw = ImageDraw.Draw(img)
    draw.rectangle([40, 40, 160, 160], fill=(220, 20, 60))
    draw.ellipse([60, 60, 140, 140], fill=(255, 215, 0))
    
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=95)
    return buf.getvalue()


@pytest.fixture
def unrelated_image_bytes():
    """Generate an entirely different synthetic JPEG image."""
    img = Image.new("RGB", (200, 200), color=(34, 139, 34))
    draw = ImageDraw.Draw(img)
    draw.polygon([(20, 180), (100, 20), (180, 180)], fill=(138, 43, 226))
    
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=95)
    return buf.getvalue()
