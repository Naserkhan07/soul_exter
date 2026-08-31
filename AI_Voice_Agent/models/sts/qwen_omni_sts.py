"""Qwen Omni Speech-to-Speech via a hosted server.

The heavy Qwen Omni model does NOT run here. It runs on a server (your own
GPU PC, or a Kaggle notebook) that exposes a simple HTTP endpoint:

    POST /sts
      multipart:  file=<person speech WAV 16k>, system=<system prompt>
      plus form fields: history=[{"role":..,"text":..}, ...]
    -> JSON:      {"text": "<recognised>", "audio_b64": "<reply audio>"}

This client just forwards local audio to that server and returns the spoken
reply. Set the server URL in config `sts.qwen_omni.url` (or the `qwen_url` key).
"""

from __future__ import annotations

import base64
import json

import requests

from ..base import STSBase, STSResult


class QwenOmniSTS(STSBase):
    name = "qwen_omni"

    def __init__(self, cfg: dict, url: str = "") -> None:
        self.url = (url or cfg.get("url", "http://127.0.0.1:8501/sts")).rstrip("/")

    def converse(self, audio_bytes: bytes, system_prompt: str,
                 history: list[dict]) -> STSResult:
        resp = requests.post(
            self.url,
            files={"file": ("speech.wav", audio_bytes, "audio/wav")},
            data={
                "system": system_prompt,
                "history": json.dumps(history),
            },
            timeout=120,
        )
        resp.raise_for_status()
        data = resp.json()
        return STSResult(
            text=data.get("text", ""),
            reply_text=data.get("text", ""),
            audio=base64.b64decode(data.get("audio_b64", "") or ""),
            language=data.get("language", "auto"),
        )
