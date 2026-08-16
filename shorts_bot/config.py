from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

from .errors import ConfigurationError

_TRUE_VALUES = {"1", "true", "yes", "on"}
_FALSE_VALUES = {"0", "false", "no", "off", ""}


def _bool_env(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in _TRUE_VALUES:
        return True
    if normalized in _FALSE_VALUES:
        return False
    raise ConfigurationError(f"{name} must be true or false, not {value!r}.")


def _int_env(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise ConfigurationError(f"{name} must be an integer.") from exc


def _user_ids(value: str | None) -> frozenset[int]:
    if not value:
        return frozenset()
    try:
        return frozenset(int(item.strip()) for item in value.split(",") if item.strip())
    except ValueError as exc:
        raise ConfigurationError("ALLOWED_TELEGRAM_USER_IDS must contain numeric IDs.") from exc


@dataclass(frozen=True, slots=True)
class Settings:
    telegram_bot_token: str
    allowed_telegram_user_ids: frozenset[int]
    openai_api_key: str
    openai_model: str
    openai_transcription_model: str
    youtube_client_secrets_file: Path
    youtube_token_file: Path
    youtube_privacy_status: str
    auto_upload: bool
    clip_duration_seconds: int
    max_urls_per_command: int
    work_dir: Path
    database_path: Path
    keep_work_files: bool
    rights_acknowledged: bool

    @classmethod
    def from_env(cls, env_file: str | Path | None = ".env") -> Settings:
        if env_file:
            load_dotenv(env_file, override=False)

        work_dir = Path(os.getenv("WORK_DIR", "work")).expanduser()
        database_path = Path(os.getenv("DATABASE_PATH", str(work_dir / "jobs.db"))).expanduser()
        settings = cls(
            telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN", "").strip(),
            allowed_telegram_user_ids=_user_ids(os.getenv("ALLOWED_TELEGRAM_USER_IDS")),
            openai_api_key=os.getenv("OPENAI_API_KEY", "").strip(),
            openai_model=os.getenv("OPENAI_MODEL", "gpt-4o-mini").strip(),
            openai_transcription_model=os.getenv("OPENAI_TRANSCRIPTION_MODEL", "whisper-1").strip(),
            youtube_client_secrets_file=Path(
                os.getenv("YOUTUBE_CLIENT_SECRETS_FILE", "client_secret.json")
            ).expanduser(),
            youtube_token_file=Path(
                os.getenv("YOUTUBE_TOKEN_FILE", "youtube_token.json")
            ).expanduser(),
            youtube_privacy_status=os.getenv("YOUTUBE_PRIVACY_STATUS", "private").strip().lower(),
            auto_upload=_bool_env("AUTO_UPLOAD", False),
            clip_duration_seconds=_int_env("CLIP_DURATION_SECONDS", 25),
            max_urls_per_command=_int_env("MAX_URLS_PER_COMMAND", 5),
            work_dir=work_dir,
            database_path=database_path,
            keep_work_files=_bool_env("KEEP_WORK_FILES", True),
            rights_acknowledged=_bool_env("RIGHTS_ACKNOWLEDGED", False),
        )
        settings.validate_common()
        return settings

    def validate_common(self) -> None:
        if not 20 <= self.clip_duration_seconds <= 30:
            raise ConfigurationError("CLIP_DURATION_SECONDS must be between 20 and 30.")
        if not 1 <= self.max_urls_per_command <= 10:
            raise ConfigurationError("MAX_URLS_PER_COMMAND must be between 1 and 10.")
        if self.youtube_privacy_status not in {"private", "unlisted", "public"}:
            raise ConfigurationError("YOUTUBE_PRIVACY_STATUS must be private, unlisted, or public.")

    def validate_pipeline(self) -> None:
        if not self.rights_acknowledged:
            raise ConfigurationError(
                "Set RIGHTS_ACKNOWLEDGED=true only after confirming you own or have "
                "permission to reuse every submitted video."
            )
        if not self.openai_api_key:
            raise ConfigurationError("OPENAI_API_KEY is required for AI clip planning.")
        if self.auto_upload and not self.youtube_token_file.exists():
            raise ConfigurationError(
                f"YouTube token not found at {self.youtube_token_file}. Run shorts-auth first."
            )

    def validate_bot(self) -> None:
        self.validate_pipeline()
        if not self.telegram_bot_token:
            raise ConfigurationError("TELEGRAM_BOT_TOKEN is required to run the bot.")
        if not self.allowed_telegram_user_ids:
            raise ConfigurationError(
                "ALLOWED_TELEGRAM_USER_IDS is required so strangers cannot upload to your channel."
            )

    def prepare_directories(self) -> None:
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.youtube_token_file.parent.mkdir(parents=True, exist_ok=True)
