from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


class Settings(BaseSettings):
    """Application settings with environment variable support."""

    # Default LLM Server (OpenAI-compatible)
    default_base_url: str = Field(
        default="http://localhost:1234/v1",
        description="Default base URL of the OpenAI-compatible LLM server",
    )
    default_api_key: str = Field(
        default="not-needed",
        description="Default API key for the LLM server",
    )
    default_model: str = Field(
        default="",
        description="Default model ID (if empty, auto-detected from server)",
    )

    # Inference settings
    concurrency_limit: int = Field(
        default=2,
        description="Maximum parallel requests to LLM server",
    )
    request_timeout: float = Field(
        default=90.0,
        description="Request timeout in seconds for LLM calls",
    )
    temperature: float = Field(
        default=0.0,
        description="Sampling temperature for deterministic copyediting",
    )

    model_config = SettingsConfigDict(
        env_prefix="DOCUMEND_",
        env_file=".env",
        extra="ignore",
    )


settings = Settings()
