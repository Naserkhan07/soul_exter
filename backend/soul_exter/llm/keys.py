"""Provider key discovery.

The desks run the built-in analyst engine with no key at all, so the floor is
never blocked on credentials. When you *do* want hosted open-source models, put
the key anywhere the host can see it:

  * an environment variable (OPENROUTER_API_KEY, TOGETHER_API_KEY, ...),
  * a `.env` file in the repo root, `backend/`, or the path in
    SOUL_EXTER_ENV_FILE,
  * or the settings panel's per-seat override.

This module loads those files once at boot and reports what it found, so the
Settings → LLM Council tab can show the operator the exact key each desk is
running with instead of an empty box.
"""
from __future__ import annotations

import os
from typing import Dict, List, Tuple

PROVIDER_ENV: Dict[str, str] = {
    "openrouter": "OPENROUTER_API_KEY",
    "together": "TOGETHER_API_KEY",
    "groq": "GROQ_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    "mistral": "MISTRAL_API_KEY",
    "openai": "OPENAI_API_KEY",
    "custom": "SOUL_EXTER_API_KEY",
    "ollama": "OLLAMA_HOST",
}

_CANDIDATES: List[str] = [
    os.environ.get("SOUL_EXTER_ENV_FILE", ""),
    ".env",
    "backend/.env",
    os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__)))), ".env"),
    os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__)))), "backend", ".env"),
    "/kaggle/working/soul_exter/.env",
]

loaded_files: List[str] = []
loaded_keys: Dict[str, str] = {}


def _parse(path: str) -> Dict[str, str]:
    out: Dict[str, str] = {}
    try:
        with open(path) as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                name, _, value = line.partition("=")
                name = name.strip().removeprefix("export ").strip()
                value = value.strip().strip('"').strip("'")
                if name and value:
                    out[name] = value
    except Exception:
        return {}
    return out


def load_env_keys() -> Tuple[List[str], Dict[str, str]]:
    """Read .env files once; real environment variables always win."""
    global loaded_files, loaded_keys
    for path in _CANDIDATES:
        if not path or not os.path.isfile(path):
            continue
        values = _parse(path)
        if not values:
            continue
        loaded_files.append(os.path.abspath(path))
        for name, value in values.items():
            loaded_keys[name] = value
            os.environ.setdefault(name, value)
    return loaded_files, loaded_keys


def report() -> Dict[str, dict]:
    """Per-provider key status: which env var, whether it is set, its value."""
    out = {}
    for provider, env_name in PROVIDER_ENV.items():
        value = os.environ.get(env_name, "")
        out[provider] = dict(env=env_name, set=bool(value), value=value, files=loaded_files)
    return out
