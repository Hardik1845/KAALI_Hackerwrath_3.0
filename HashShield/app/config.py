from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional


class Settings(BaseSettings):
    """HashShield configuration settings loaded from environment."""
    API_KEY: str = "kaali-secret-key-12345"
    HASH_THRESHOLD: int = 10
    SLA_HOURS: int = 24
    UPLOAD_MAX_MB: int = 10
    RATE_LIMIT_DEFAULT: str = "60/minute"
    MONGO_URL: Optional[str] = None
    ENVIRONMENT: str = "development"
    LOG_LEVEL: str = "INFO"

    # Web Discovery & Candidate Verification Settings
    DISCOVER_PROVIDER: str = "serpapi_lens"  # "mock" | "google_vision" | "serpapi_lens"
    DISCOVER_DAILY_LIMIT: int = 50
    FETCH_CANDIDATE_IMAGES: bool = True
    MAX_CANDIDATES_TO_VERIFY: int = 20
    CANDIDATE_FETCH_TIMEOUT: float = 5.0
    CANDIDATE_MAX_MB: int = 5
    GOOGLE_APPLICATION_CREDENTIALS: Optional[str] = None
    SERPAPI_API_KEY: Optional[str] = None

    # Neural Copy Detection (SSCD)
    ENABLE_SSCD: bool = False
    SSCD_SIMILARITY_THRESHOLD: float = 0.70

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )


settings = Settings()
