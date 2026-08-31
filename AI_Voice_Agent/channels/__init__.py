"""Channels layer — connect the agent to messaging platforms.

The agent's brain (agent/controller.py) is channel-agnostic. A Channel is just
a transport: it receives the person's text and hands the agent's reply back.

Supported channels:
  web       : a local browser chat UI (works out of the box, no accounts)
  telegram  : Telegram bot (free, via BotFather token)
  whatsapp  : WhatsApp Business Cloud API (Meta) — needs a business number
  teams     : Microsoft Teams bot (Bot Framework) — needs Azure/M365 setup
  cli       : terminal (same as main.py text mode)

The phone/loopback audio path is separate (see phone/) and also uses the same
controller.
"""

from .base import Message, Channel, ChannelBroker
from .web import WebChannel
from .telegram import TelegramChannel
from .whatsapp import WhatsAppChannel
from .teams import TeamsChannel
from .broker import build_channel, run_channel

__all__ = [
    "Message", "Channel", "ChannelBroker",
    "WebChannel", "TelegramChannel", "WhatsAppChannel", "TeamsChannel",
    "build_channel", "run_channel",
]
