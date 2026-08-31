"""Telegram channel — talk to the agent via a Telegram bot.

Free and easy to set up:
  1. Message @BotFather on Telegram -> /newbot -> get a token.
  2. Put the token in config `channels.telegram.token` (or env TELEGRAM_TOKEN).
  3. Run: python run_channel.py telegram
Then message your bot on Telegram and it replies through the same agent brain
(with per-user memory + lead capture).

Uses long-polling (getUpdates) so no public webhook / hosting is needed.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import requests

from .base import Channel

log = logging.getLogger("channels.telegram")

API = "https://api.telegram.org/bot{token}/"


class TelegramChannel(Channel):
    name = "telegram"

    def __init__(self, broker, cfg: dict | None = None):
        super().__init__(broker)
        import os
        self.cfg = cfg or {}
        self.token = self.cfg.get("token") or os.environ.get("TELEGRAM_TOKEN", "")
        self.poll_timeout = int(self.cfg.get("poll_timeout", 30))
        self._offset = 0
        self._running = False

    def _api(self, method: str, **params) -> dict:
        resp = requests.get(API.format(token=self.token) + method,
                            params=params, timeout=60)
        resp.raise_for_status()
        return resp.json()

    def _send(self, chat_id: int, text: str) -> None:
        self._api("sendMessage", chat_id=chat_id, text=text)

    def start(self) -> None:
        if not self.token:
            raise RuntimeError(
                "Telegram token missing. Set channels.telegram.token in "
                "config.yaml or TELEGRAM_TOKEN env. Get one from @BotFather.")
        self._running = True
        me = self._api("getMe")
        log.info("Telegram bot: @%s", me["result"]["username"])
        while self._running:
            try:
                updates = self._api("getUpdates", offset=self._offset,
                                    timeout=self.poll_timeout)
                for u in updates.get("result", []):
                    self._offset = u["update_id"] + 1
                    self._handle_update(u)
            except requests.RequestException as e:  # pragma: no cover
                log.warning("Telegram poll error: %s", e)
                time.sleep(3)

    def stop(self) -> None:
        self._running = False

    def _handle_update(self, update: dict) -> None:
        msg = update.get("message") or {}
        text = (msg.get("text") or "").strip()
        chat_id = msg.get("chat", {}).get("id")
        user = msg.get("from", {})
        user_id = f"tg-{chat_id}"
        name = f"{user.get('first_name','')} {user.get('last_name','')}".strip()
        if not text or chat_id is None:
            return
        if text == "/start":
            self._send(chat_id, "Hello! I'm the AI Voice Agent. Ask me anything. /reset to start over.")
            return
        if text == "/reset":
            self.end_session(user_id)
            self._send(chat_id, "Conversation reset.")
            return
        try:
            result = self.handle_text(user_id, text, name)
            reply = result.reply
            if result.lead_changes:
                reply = reply + "\n\n" + "\n".join(result.lead_changes)
            self._send(chat_id, reply)
        except Exception as e:  # pragma: no cover
            log.exception("telegram turn error")
            self._send(chat_id, f"Sorry, something went wrong: {e}")
