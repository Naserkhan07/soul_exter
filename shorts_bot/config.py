from __future__ import annotations

import os
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

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


def _read_channel_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        with path.open("rb") as config_file:
            return tomllib.load(config_file)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ConfigurationError(f"Could not read channel configuration {path}: {exc}") from exc


def _nested_string(config: dict[str, Any], section: str, key: str) -> str:
    section_value = config.get(section, {})
    if not isinstance(section_value, dict):
        return ""
    return str(section_value.get(key, "")).strip()


@dataclass(frozen=True, slots=True)
class Settings:
    telegram_bot_token: str
    allowed_telegram_user_ids: frozenset[int]
    groq_api_key: str
    groq_model: str
    groq_transcription_model: str
    channel_config_file: Path
    youtube_channel_id: str
    youtube_client_secrets_file: Path
    youtube_token_file: Path
    youtube_privacy_status: str
    upload_youtube: bool
    instagram_user_id: str
    instagram_access_token: str
    instagram_graph_api_version: str
    upload_instagram: bool
    clip_duration_seconds: int
    max_urls_per_command: int
    work_dir: Path
    database_path: Path
    keep_work_files: bool
    rights_acknowledged: bool
    links_file: Path
    downloaded_links_log: Path
    links_poll_seconds: int

    @classmethod
    def from_env(cls, env_file: str | Path | None = ".env") -> Settings:
        if env_file:
            load_dotenv(env_file, override=False)

        work_dir = Path(os.getenv("WORK_DIR", "work")).expanduser()
        database_path = Path(os.getenv("DATABASE_PATH", str(work_dir / "jobs.db"))).expanduser()
        channel_config_file = Path(os.getenv("CHANNEL_CONFIG_FILE", "channels.toml")).expanduser()
        channel_config = _read_channel_config(channel_config_file)
        legacy_auto_upload = _bool_env("AUTO_UPLOAD", False)

        settings = cls(
            telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN", "").strip(),
            allowed_telegram_user_ids=_user_ids(os.getenv("ALLOWED_TELEGRAM_USER_IDS")),
            groq_api_key=os.getenv("GROQ_API_KEY", "").strip(),
            groq_model=os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile").strip(),
            groq_transcription_model=os.getenv(
                "GROQ_TRANSCRIPTION_MODEL", "whisper-large-v3-turbo"
            ).strip(),
            channel_config_file=channel_config_file,
            youtube_channel_id=(
                os.getenv("YOUTUBE_CHANNEL_ID", "").strip()
                or _nested_string(channel_config, "youtube", "channel_id")
            ),
            youtube_client_secrets_file=Path(
                os.getenv("YOUTUBE_CLIENT_SECRETS_FILE", "client_secret.json")
            ).expanduser(),
            youtube_token_file=Path(
                os.getenv("YOUTUBE_TOKEN_FILE", "youtube_token.json")
            ).expanduser(),
            youtube_privacy_status=os.getenv("YOUTUBE_PRIVACY_STATUS", "public").strip().lower(),
            upload_youtube=_bool_env("UPLOAD_YOUTUBE", legacy_auto_upload),
            instagram_user_id=(
                os.getenv("INSTAGRAM_USER_ID", "").strip()
                or _nested_string(channel_config, "instagram", "user_id")
            ),
            instagram_access_token=os.getenv("INSTAGRAM_ACCESS_TOKEN", "").strip(),
            instagram_graph_api_version=os.getenv("INSTAGRAM_GRAPH_API_VERSION", "v25.0").strip(),
            upload_instagram=_bool_env("UPLOAD_INSTAGRAM", False),
            clip_duration_seconds=_int_env("CLIP_DURATION_SECONDS", 25),
            max_urls_per_command=_int_env("MAX_URLS_PER_COMMAND", 5),
            work_dir=work_dir,
            database_path=database_path,
            keep_work_files=_bool_env("KEEP_WORK_FILES", True),
            rights_acknowledged=_bool_env("RIGHTS_ACKNOWLEDGED", False),
            links_file=Path(os.getenv("LINKS_FILE", "links.txt")).expanduser(),
            downloaded_links_log=Path(
                os.getenv("DOWNLOADED_LINKS_LOG", str(work_dir / "downloaded-links.log"))
            ).expanduser(),
            links_poll_seconds=_int_env("LINKS_POLL_SECONDS", 30),
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
        if not re.fullmatch(r"v\d+\.\d+", self.instagram_graph_api_version):
            raise ConfigurationError("INSTAGRAM_GRAPH_API_VERSION must look like v25.0.")
        if not 5 <= self.links_poll_seconds <= 3600:
            raise ConfigurationError("LINKS_POLL_SECONDS must be between 5 and 3600.")

    def validate_pipeline(self) -> None:
        if not self.rights_acknowledged:
            raise ConfigurationError(
                "Set RIGHTS_ACKNOWLEDGED=true only after confirming you own or have "
                "permission to reuse every submitted video."
            )
        if not self.groq_api_key:
            raise ConfigurationError("GROQ_API_KEY is required for AI clip planning.")
        if self.upload_youtube:
            if not self.youtube_channel_id:
                raise ConfigurationError(
                    f"Add your YouTube channel_id to {self.channel_config_file}."
                )
            if not self.youtube_token_file.exists():
                raise ConfigurationError(
                    f"YouTube OAuth token not found at {self.youtube_token_file}. "
                    "Run shorts-auth first."
                )
        if self.upload_instagram:
            if not self.instagram_user_id:
                raise ConfigurationError(
                    f"Add your Instagram professional account user_id to "
                    f"{self.channel_config_file}."
                )
            if not self.instagram_access_token:
                raise ConfigurationError(
                    "INSTAGRAM_ACCESS_TOKEN is required for Instagram publishing."
                )

    def validate_bot(self) -> None:
        self.validate_pipeline()
        if not self.telegram_bot_token:
            raise ConfigurationError("TELEGRAM_BOT_TOKEN is required to run the bot.")
        if not self.allowed_telegram_user_ids:
            raise ConfigurationError(
                "ALLOWED_TELEGRAM_USER_IDS is required so strangers cannot publish "
                "to your channels."
            )

    def validate_file_queue(self) -> None:
        self.validate_pipeline()
        if not self.upload_youtube and not self.upload_instagram:
            raise ConfigurationError(
                "Enable UPLOAD_YOUTUBE or UPLOAD_INSTAGRAM for the automated link queue."
            )

    def prepare_directories(self) -> None:
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.youtube_token_file.parent.mkdir(parents=True, exist_ok=True)
        self.links_file.parent.mkdir(parents=True, exist_ok=True)
        self.links_file.touch(exist_ok=True)
        self.downloaded_links_log.parent.mkdir(parents=True, exist_ok=True)
