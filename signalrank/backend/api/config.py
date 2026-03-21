from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    nextauth_secret: str
    environment: str = "development"
    allowed_origins: list[str] = ["http://localhost:3000"]
    openrouter_api_key: str = ""


settings = Settings()
