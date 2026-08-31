#!/usr/bin/env python3
"""Run the agent on a messaging channel (text).

Channels: web | telegram | whatsapp | teams | cli

Examples:
    python run_channel.py web          # browser chat on http://localhost:8770
    python run_channel.py telegram     # Telegram bot (needs a BotFather token)
    python run_channel.py whatsapp     # WhatsApp Business API webhook
    python run_channel.py teams        # Microsoft Teams bot endpoint
    python run_channel.py cli          # terminal chat
    python run_channel.py web --mock   # fully offline
"""

from __future__ import annotations

import argparse

from config import load_config
from channels.broker import run_channel

AVAILABLE = ["web", "telegram", "whatsapp", "teams", "cli"]


def main() -> None:
    ap = argparse.ArgumentParser(description="Run the agent on a channel")
    ap.add_argument("channel", choices=AVAILABLE,
                    help="which channel to run on")
    ap.add_argument("--mock", action="store_true",
                    help="force all providers to mock (fully offline)")
    ap.add_argument("--config", default=None, help="path to config.yaml")
    ap.add_argument("--port", default=None, help="override the channel port (web/wa/teams)")
    args = ap.parse_args()

    cfg = load_config(args.config)
    if args.port:
        ch = cfg.setdefault("channels", {}).setdefault(args.channel, {})
        ch["port"] = int(args.port)
    run_channel(args.channel, cfg, mock=args.mock)


if __name__ == "__main__":
    main()
