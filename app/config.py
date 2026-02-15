from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DATABASE_URL: str = "sqlite+aiosqlite:///./genleads.db"
    HEADLESS: bool = True
    SCRAPE_DELAY_MIN: float = 1.5
    SCRAPE_DELAY_MAX: float = 3.0
    MAX_SCROLL_COUNT: int = 25

    class Config:
        env_file = ".env"


settings = Settings()
