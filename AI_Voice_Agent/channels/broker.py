"""Build and run channels from config."""

from __future__ import annotations

import logging
import time

from config import load_config, resolve_keys
from main import build_controller
from .base import ChannelBroker

log = logging.getLogger("channels.broker")


def _controller_factory(cfg: dict, mock: bool = False):
    """Return a zero-arg callable that builds a fresh Controller per session."""
    def _new():
        return build_controller(cfg, mock)
    return _new


def build_channel(name: str, broker: ChannelBroker, cfg: dict, mock: bool = False) -> Channel:
    """Instantiate one channel by name."""
    name = name.lower()
    if name == "web":
        from .web import WebChannel
        return WebChannel(broker, cfg.get("web", {}), mock=mock)
    if name == "telegram":
        from .telegram import TelegramChannel
        return TelegramChannel(broker, cfg.get("telegram", {}))
    if name == "whatsapp":
        from .whatsapp import WhatsAppChannel
        return WhatsAppChannel(broker, cfg.get("whatsapp", {}))
    if name == "teams":
        from .teams import TeamsChannel
        return TeamsChannel(broker, cfg.get("teams", {}))
    if name == "cli":
        from .cli import CLIChatChannel
        return CLIChatChannel(broker)
    raise ValueError(f"Unknown channel: {name}")


def run_channel(channel_name: str, cfg: dict, mock: bool = False) -> None:
    """Start the agent on a single channel and block."""
    keys = resolve_keys(cfg)  # noqa: F841 (validate keys)
    broker = ChannelBroker(_controller_factory(cfg, mock))
    channel = build_channel(channel_name, broker, cfg, mock)
    broker.register(channel)
    print(f"AI Voice Agent | channel: {channel.name}")
    try:
        channel.start()
        # Block for non-blocking channels (web / whatsapp / teams run their
        # server on a background thread). Telegram/CLI block inside start().
        while getattr(channel, "running", False):
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        channel.stop()
