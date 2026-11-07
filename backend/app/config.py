from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """App settings. Override any field via env var or a .env file."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Market metadata (events, markets, outcomes, prices)
    gamma_api_url: str = "https://gamma-api.polymarket.com"
    # Order book / pricing
    clob_api_url: str = "https://clob.polymarket.com"
    # Trades tied to wallets (v1 is retired; v2 is the live API)
    data_api_url: str = "https://data-api.polymarket.com/v2"

    http_timeout_seconds: float = 10.0


@lru_cache
def get_settings() -> Settings:
    return Settings()
