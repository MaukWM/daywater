import os

from dotenv import load_dotenv


class Settings:
    def __init__(self) -> None:
        load_dotenv()

        self.DEBUG: bool = os.getenv("DEBUG", "false").lower() in ("true", "1", "t", "yes")
        self.LOG_LEVEL: str = os.getenv("LOG_LEVEL", "DEBUG" if self.DEBUG else "INFO")
        self.LOG_FORMAT: str = os.getenv("LOG_FORMAT", "console")


settings = Settings()
