"""CLI channel — terminal chat through the shared Channel interface.

Same as main.py text mode, but routed through the broker so every channel
shares identical agent behaviour. Type /bye, /reset, /help.
"""

from __future__ import annotations

import logging

from .base import Channel

log = logging.getLogger("channels.cli")


class CLIChatChannel(Channel):
    name = "cli"

    def start(self) -> None:
        user_id = "cli"
        print("AI Voice Agent (CLI). Commands: /bye  /reset  /help")
        while True:
            try:
                line = input("\nYou: ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if not line:
                continue
            if line in ("/bye", "/exit", "/quit"):
                break
            if line == "/reset":
                self.end_session(user_id)
                print("[reset]")
                continue
            if line == "/help":
                print("/bye end | /reset new conversation")
                continue
            result = self.handle_text(user_id, line)
            print(f"Agent: {result.reply}")
            for c in result.lead_changes:
                print(f"       {c}")
        self.end_session(user_id)

    def stop(self) -> None:
        pass
