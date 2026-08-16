from pathlib import Path

import pytest

from shorts_bot.config import Settings
from shorts_bot.errors import ConfigurationError


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    names = [
        "TELEGRAM_BOT_TOKEN",
        "ALLOWED_TELEGRAM_USER_IDS",
        "OPENAI_API_KEY",
        "AUTO_UPLOAD",
        "CLIP_DURATION_SECONDS",
        "MAX_URLS_PER_COMMAND",
        "WORK_DIR",
        "DATABASE_PATH",
        "KEEP_WORK_FILES",
        "RIGHTS_ACKNOWLEDGED",
        "YOUTUBE_PRIVACY_STATUS",
    ]
    for name in names:
        monkeypatch.delenv(name, raising=False)


def test_reads_valid_settings(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("ALLOWED_TELEGRAM_USER_IDS", "12, 34")
    monkeypatch.setenv("OPENAI_API_KEY", "openai-key")
    monkeypatch.setenv("RIGHTS_ACKNOWLEDGED", "true")
    monkeypatch.setenv("WORK_DIR", str(tmp_path / "work"))

    settings = Settings.from_env(env_file=None)
    settings.validate_bot()

    assert settings.allowed_telegram_user_ids == frozenset({12, 34})
    assert settings.clip_duration_seconds == 25
    assert settings.auto_upload is False


def test_rejects_duration_outside_shorts_range(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLIP_DURATION_SECONDS", "31")

    with pytest.raises(ConfigurationError, match="between 20 and 30"):
        Settings.from_env(env_file=None)


def test_requires_rights_acknowledgement(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "key")
    settings = Settings.from_env(env_file=None)

    with pytest.raises(ConfigurationError, match="RIGHTS_ACKNOWLEDGED"):
        settings.validate_pipeline()
