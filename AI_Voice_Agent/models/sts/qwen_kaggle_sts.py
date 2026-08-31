"""Qwen Omni Speech-to-Speech hosted on a Kaggle GPU.

Same client as QwenOmniSTS but tuned for the free Kaggle-hosted endpoint
(which runs behind Kaggle's public proxy / ngrok-style tunnel, so the URL is
dynamic). Set the current URL in config `sts.qwen_kaggle.url` or the `qwen_url`
key.

The matching Kaggle server notebook is in:
    scripts/kaggle/qwen_omni_server.ipynb
"""

from __future__ import annotations

from ..base import STSBase, STSResult
from .qwen_omni_sts import QwenOmniSTS


class QwenKaggleSTS(QwenOmniSTS):
    name = "qwen_kaggle"

    def __init__(self, cfg: dict, url: str = "") -> None:
        self.url = (url or cfg.get("url", "")).rstrip("/")
        if not self.url:
            raise RuntimeError(
                "No Qwen Kaggle URL configured. Start scripts/kaggle/qwen_omni_server.ipynb "
                "on Kaggle, then set sts.qwen_kaggle.url (or the qwen_url key) to its tunnel URL."
            )
