import uuid
import logging
import time
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone, timedelta
from urllib.parse import urlparse
import tldextract
from app.config import settings

logger = logging.getLogger("hashshield.discovery")


class DiscoveryProvider:
    """Abstract interface for reverse image discovery providers."""
    async def discover(self, image_bytes: bytes, phash: str, image_url: Optional[str] = None) -> List[Dict[str, Any]]:
        raise NotImplementedError


class MockDiscoveryProvider(DiscoveryProvider):
    """
    Default mock discovery provider returning realistic candidate URLs.
    Includes an exact copy, a cropped/recompressed copy, and an unrelated entry.
    """
    async def discover(self, image_bytes: bytes, phash: str, image_url: Optional[str] = None) -> List[Dict[str, Any]]:
        return [
            {
                "candidate_id": f"cand_{uuid.uuid4().hex[:10]}",
                "page_url": "https://anon-leak-hub.cz/post/v88291",
                "image_url": "https://anon-leak-hub.cz/cdn/master_copy.jpg",
                "domain": "anon-leak-hub.cz",
                "match_type": "full",
                "simulated_synthetic": "master"
            },
            {
                "candidate_id": f"cand_{uuid.uuid4().hex[:10]}",
                "page_url": "https://dark-archive.ru/threads/9128",
                "image_url": "https://dark-archive.ru/uploads/derivative_thumb.jpg",
                "domain": "dark-archive.ru",
                "match_type": "partial",
                "simulated_synthetic": "derivative"
            },
            {
                "candidate_id": f"cand_{uuid.uuid4().hex[:10]}",
                "page_url": "https://unrelated-forum.net/topic/33",
                "image_url": "https://unrelated-forum.net/img/nature_stock.jpg",
                "domain": "unrelated-forum.net",
                "match_type": "similar",
                "simulated_synthetic": "unrelated"
            }
        ]


class GoogleVisionDiscoveryProvider(DiscoveryProvider):
    """
    Real-world reverse image search provider using Google Cloud Vision Web Detection.
    Scans the public web index for fullMatchingImages, partialMatchingImages, and pagesWithMatchingImages.
    """
    def __init__(self):
        try:
            from google.cloud import vision
            self.client = vision.ImageAnnotatorClient()
            self.enabled = True
        except Exception as e:
            logger.warning(f"Google Cloud Vision not initialized ({e}).")
            self.enabled = False

    async def discover(self, image_bytes: bytes, phash: str, image_url: Optional[str] = None) -> List[Dict[str, Any]]:
        if not self.enabled:
            raise RuntimeError("Google Vision search is not configured. Set GOOGLE_APPLICATION_CREDENTIALS and DISCOVER_PROVIDER=google_vision.")

        from google.cloud import vision
        image = vision.Image(content=image_bytes)
        response = self.client.web_detection(image=image)
        if response.error.message:
            raise RuntimeError(f"Google Vision web detection failed: {response.error.message}")
        web_detection = response.web_detection

        candidates: List[Dict[str, Any]] = []

        # 1. Full Matching Images
        for img in web_detection.full_matching_images:
            url = img.url
            domain = tldextract.extract(url).registered_domain or urlparse(url).netloc
            candidates.append({
                "candidate_id": f"cand_{uuid.uuid4().hex[:10]}",
                "page_url": url,
                "image_url": url,
                "domain": domain,
                "match_type": "full"
            })

        # 2. Partial Matching Images
        for img in web_detection.partial_matching_images:
            url = img.url
            domain = tldextract.extract(url).registered_domain or urlparse(url).netloc
            candidates.append({
                "candidate_id": f"cand_{uuid.uuid4().hex[:10]}",
                "page_url": url,
                "image_url": url,
                "domain": domain,
                "match_type": "partial"
            })

        # 3. Pages with Matching Images
        for page in web_detection.pages_with_matching_images:
            page_url = page.url
            domain = tldextract.extract(page_url).registered_domain or urlparse(page_url).netloc
            img_url = page_url
            if page.full_matching_images:
                img_url = page.full_matching_images[0].url
            elif page.partial_matching_images:
                img_url = page.partial_matching_images[0].url

            candidates.append({
                "candidate_id": f"cand_{uuid.uuid4().hex[:10]}",
                "page_url": page_url,
                "image_url": img_url,
                "domain": domain,
                "match_type": "full"
            })

        return candidates


class SerpApiLensDiscoveryProvider(DiscoveryProvider):
    """
    Reverse image discovery via SerpApi Google Lens engine.
    Supports API key authentication with 100 free searches.
    """
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or settings.SERPAPI_API_KEY

    async def discover(self, image_bytes: bytes, phash: str, image_url: Optional[str] = None) -> List[Dict[str, Any]]:
        if not self.api_key:
            raise RuntimeError("SERPAPI_API_KEY is not configured. Add it to HashShield/.env to enable web image search.")

        import httpx
        candidates: List[Dict[str, Any]] = []

        try:
            async with httpx.AsyncClient(timeout=25.0) as client:
                if image_url and image_url != "string" and image_url.startswith(("http://", "https://")):
                    params = {
                        "engine": "google_lens",
                        "url": image_url,
                        "api_key": self.api_key,
                        "no_cache": "true"
                    }
                    res = await client.get("https://serpapi.com/search.json", params=params)
                else:
                    # Upload local image bytes to SerpApi Image API
                    upload_bytes = image_bytes
                    if len(upload_bytes) > 480 * 1024:
                        from PIL import Image
                        import io
                        img = Image.open(io.BytesIO(upload_bytes)).convert("RGB")
                        img.thumbnail((800, 800), Image.Resampling.LANCZOS)
                        buf = io.BytesIO()
                        img.save(buf, format="JPEG", quality=80)
                        upload_bytes = buf.getvalue()

                    upload_res = await client.post(
                        "https://serpapi.com/image",
                        files={"image": ("upload.jpg", upload_bytes, "image/jpeg")},
                        data={"api_key": self.api_key}
                    )
                    if upload_res.status_code != 200:
                        logger.warning(f"SerpApi image upload failed: {upload_res.status_code} {upload_res.text[:150]}")
                        raise RuntimeError(f"SerpApi image upload failed (HTTP {upload_res.status_code}). Check the key, quota and provider status.")

                    image_id = upload_res.json().get("image_id")
                    if not image_id:
                        raise RuntimeError("SerpApi did not return an image ID for the uploaded image.")

                    params = {
                        "engine": "google_lens",
                        "image_id": image_id,
                        "api_key": self.api_key,
                        "no_cache": "true"
                    }
                    res = await client.get("https://serpapi.com/search.json", params=params)

                if res.status_code != 200:
                    logger.warning(f"SerpApi search returned {res.status_code}: {res.text[:200]}")
                    raise RuntimeError(f"SerpApi search failed (HTTP {res.status_code}). Check the key, quota and provider status.")

                result_json = res.json()
                if result_json.get("error"):
                    raise RuntimeError(f"SerpApi Google Lens error: {result_json['error']}")
                visual_matches = result_json.get("visual_matches", [])

                for match in visual_matches[:20]:
                    link = match.get("link") or match.get("source")
                    if not link:
                        continue
                    domain = tldextract.extract(link).registered_domain or urlparse(link).netloc
                    img_url = match.get("thumbnail") or link
                    candidates.append({
                        "candidate_id": f"cand_{uuid.uuid4().hex[:10]}",
                        "page_url": link,
                        "image_url": img_url,
                        "domain": domain,
                        "match_type": "full"
                    })

        except Exception as e:
            logger.error(f"Error querying SerpApi Google Lens: {e}")
            if isinstance(e, RuntimeError):
                raise
            raise RuntimeError("Could not contact SerpApi Google Lens. Check the network connection and provider settings.") from e

        return candidates


# ==============================================================================
# CACHING & DAILY RATE LIMIT TRACKER
# ==============================================================================

class DiscoveryCache:
    """
    24-hour cache keyed by perceptual hash (pHash).
    Stores candidate metadata and URLs only. Never stores image bytes.
    """
    def __init__(self, ttl_hours: int = 24):
        self.ttl = timedelta(hours=ttl_hours)
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._daily_counts: Dict[str, int] = {}  # "YYYY-MM-DD" -> count

    def get(self, phash: str) -> Optional[List[Dict[str, Any]]]:
        entry = self._cache.get(phash)
        if not entry:
            return None
        if datetime.now(timezone.utc) > entry["expires_at"]:
            del self._cache[phash]
            return None
        return entry["candidates"]

    def set(self, phash: str, candidates: List[Dict[str, Any]]):
        self._cache[phash] = {
            "candidates": candidates,
            "expires_at": datetime.now(timezone.utc) + self.ttl
        }

    def check_and_increment_daily_quota(self, max_limit: int = 50) -> int:
        """Enforce daily discovery limit. Returns remaining daily scans."""
        today_key = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        current_count = self._daily_counts.get(today_key, 0)
        if current_count >= max_limit:
            raise ValueError(f"Daily discovery limit of {max_limit} requests reached. Try again tomorrow.")
        self._daily_counts[today_key] = current_count + 1
        return max_limit - (current_count + 1)

    def get_remaining_quota(self, max_limit: int = 50) -> int:
        today_key = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        current = self._daily_counts.get(today_key, 0)
        return max(0, max_limit - current)

    def clear(self):
        self._cache.clear()
        self._daily_counts.clear()


# Global singletons
discovery_cache = DiscoveryCache()

def get_discovery_provider() -> DiscoveryProvider:
    provider_name = settings.DISCOVER_PROVIDER.lower().strip()
    if provider_name == "google_vision":
        return GoogleVisionDiscoveryProvider()
    elif provider_name in ("serpapi", "serpapi_lens"):
        return SerpApiLensDiscoveryProvider()
    elif provider_name == "mock":
        return MockDiscoveryProvider()
    raise RuntimeError(f"Unsupported DISCOVER_PROVIDER: {settings.DISCOVER_PROVIDER}")
