from functools import lru_cache

from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict

load_dotenv()


class Settings(BaseSettings):
    """Application configuration, sourced from environment variables / .env."""

    model_config = SettingsConfigDict(
        env_file=".env", extra="ignore", protected_namespaces=()
    )

    database_url: str = "postgresql+psycopg://buren:buren@localhost:5432/buren_chatbot"

    model_api_key: str = ""
    model: str = "gemini-2.0-flash"

    mcp_server_path: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
