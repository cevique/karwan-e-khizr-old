import os
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Application Settings class using Pydantic Settings.
    Loads variables from system environment first, then from the local .env file.
    """

    ENV: str = "development"
    DEBUG: bool = True

    # Required settings (no defaults to avoid hardcoding secrets or credentials)
    DATABASE_URL: str
    SECRET_KEY: str

    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30

    # Configure Pydantic Settings to load from .env file inside backend directory
    model_config = SettingsConfigDict(
        env_file=os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"
        ),
        env_file_encoding="utf-8",
        extra="ignore",
    )


# Instantiate settings so it is easily importable across the backend application
settings = Settings()
