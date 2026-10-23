from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional


import os
_DOTENV_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")

class Settings(BaseSettings):
    """Emergency SOS configuration settings loaded from environment."""
    API_KEY: str = "kaali-secret-key-12345"
    HOST: str = "127.0.0.1"
    PORT: int = 8001
    ENVIRONMENT: str = "development"
    BASE_URL: str = "http://127.0.0.1:8001"
    LOG_LEVEL: str = "INFO"

    # Auto-Escalation Timer (in seconds, default 60s per PRD FR-4.7)
    ESCALATION_TIMEOUT_SECONDS: int = 60

    # SMS Provider ("mock" | "twilio")
    SMS_PROVIDER: str = "mock"
    TWILIO_ACCOUNT_SID: Optional[str] = None
    TWILIO_AUTH_TOKEN: Optional[str] = None
    TWILIO_PHONE_NUMBER: Optional[str] = None

    # Encryption (Fernet AES-256 for audio at rest)
    AUDIO_ENCRYPTION_KEY: str = "5Y_Xj5K9x_9e4GZ07Cg4bE2z7vLq1n6x8m0w4k8y_1I="
    DEFAULT_CANCEL_PASSPHRASE: str = "sunflower"
    MAX_AUDIO_SIZE_MB: int = 15

    model_config = SettingsConfigDict(
        env_file=_DOTENV_PATH,
        env_file_encoding="utf-8",
        extra="ignore"
    )


settings = Settings()
