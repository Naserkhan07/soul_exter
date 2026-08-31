"""Load config.yaml, merge with .env / environment variables, resolve API keys."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

_ROOT = Path(__file__).resolve().parent.parent


def _load_env(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))


def load_config(path: str | Path | None = None) -> dict[str, Any]:
    path = Path(path) if path else _ROOT / "config" / "config.yaml"
    _load_env(_ROOT / ".env")
    with open(path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    return cfg


def resolve_keys(cfg: dict[str, Any]) -> dict[str, str]:
    """API keys from env vars, falling back to config keys section."""
    mapping = {
        "openai": "OPENAI_API_KEY",
        "deepgram": "DEEPGRAM_API_KEY",
        "gemini": "GEMINI_API_KEY",
        "elevenlabs": "ELEVENLABS_API_KEY",
        "qwen_url": "QWEN_URL",
    }
    keys = cfg.get("keys", {}) or {}
    resolved = {}
    for name, env in mapping.items():
        val = os.environ.get(env, "") or keys.get(name, "")
        resolved[name] = val
    return resolved
