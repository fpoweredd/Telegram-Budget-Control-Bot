"""Typed application settings loaded from environment variables and ``.env``."""

from datetime import time
from pathlib import Path
from typing import Annotated, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, SecretStr, ValidationError, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

__all__ = ["ConfigError", "Language", "Settings", "load_settings"]

Language = Literal["en", "ru"]


class ConfigError(RuntimeError):
    """Configuration is missing or invalid. The message lists every problem."""


def _split_csv(value: object) -> object:
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    return value


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    telegram_bot_token: SecretStr
    google_api_key: SecretStr
    gemini_model: str = "gemini-flash-latest"
    gemini_timeout_seconds: float = Field(default=60.0, gt=0)

    admin_ids: Annotated[tuple[int, ...], NoDecode] = Field(min_length=1)
    user_ids: Annotated[tuple[int, ...], NoDecode] = ()

    language: Language = "en"
    currency: str = Field(default="€", min_length=1, max_length=5)
    timezone: str = "Europe/Madrid"
    report_time: time = time(23, 59)
    reminder_times: Annotated[tuple[time, ...], NoDecode] = (time(14, 0), time(21, 0))
    default_target_days: int = Field(default=30, ge=1, le=366)

    db_path: Path = Path("budget.db")
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    @field_validator("admin_ids", "user_ids", "reminder_times", mode="before")
    @classmethod
    def _parse_csv(cls, value: object) -> object:
        return _split_csv(value)

    @field_validator("admin_ids", "user_ids")
    @classmethod
    def _positive_ids(cls, ids: tuple[int, ...]) -> tuple[int, ...]:
        if any(user_id <= 0 for user_id in ids):
            raise ValueError("Telegram user ids must be positive numbers")
        return ids

    @field_validator("timezone")
    @classmethod
    def _known_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as e:
            raise ValueError(f"unknown time zone {value!r}, use an IANA name like 'Europe/Madrid'") from e
        return value

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)

    @property
    def member_ids(self) -> tuple[int, ...]:
        """Admins and users, without duplicates, in a stable order."""
        return tuple(dict.fromkeys((*self.admin_ids, *self.user_ids)))


def load_settings() -> Settings:
    """Load settings or raise ConfigError with one readable line per problem."""
    try:
        return Settings()
    except ValidationError as e:
        lines = [f"  - {'.'.join(str(p) for p in err['loc']).upper()}: {err['msg']}" for err in e.errors()]
        raise ConfigError("Invalid configuration:\n" + "\n".join(lines) + "\nSee .env.example.") from e
