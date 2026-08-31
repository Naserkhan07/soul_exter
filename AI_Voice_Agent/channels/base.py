"""Base classes for messaging channels and the message broker."""

from __future__ import annotations

import logging
import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

log = logging.getLogger("channels.base")


@dataclass
class Message:
    """One person message from any channel, and the agent's reply."""
    channel: str = "unknown"
    user_id: str = "default"       # per-person id within the channel
    user_name: str = ""
    text: str = ""
    reply: str = ""                # filled by the broker
    lead_changes: list[str] = field(default_factory=list)
    lead: dict = field(default_factory=dict)


class Channel(ABC):
    """A transport the agent can talk through. One Channel = one platform."""

    name = "base"

    def __init__(self, broker: "ChannelBroker"):
        self.broker = broker
        # Per-person conversation controllers (so each person has their own
        # memory + lead, like separate phone calls).
        self._sessions: dict[str, "object"] = {}
        self._lock = threading.Lock()

    def session(self, user_id: str):
        """Get (or create) a per-user agent Controller for this channel."""
        with self._lock:
            ctrl = self._sessions.get(user_id)
            if ctrl is None:
                ctrl = self.broker.new_controller()
                opening = ctrl.start_call()
                if opening:
                    log.info("[%s] new session %s -> opening: %s",
                             self.name, user_id, opening)
                self._sessions[user_id] = ctrl
            return ctrl

    def handle_text(self, user_id: str, text: str,
                    user_name: str = "") -> Message:
        """Run one turn through the agent; returns the reply Message."""
        msg = Message(channel=self.name, user_id=user_id,
                      user_name=user_name, text=text)
        ctrl = self.session(user_id)
        changes = ctrl.update_lead(text)
        msg.lead_changes = changes
        msg.reply = ctrl.handle_utterance(text)
        msg.lead = ctrl.lead.to_dict()
        return msg

    def end_session(self, user_id: str) -> None:
        with self._lock:
            ctrl = self._sessions.pop(user_id, None)
            if ctrl:
                ctrl.end_call()

    @abstractmethod
    def start(self) -> None:
        """Begin receiving messages (blocking or background)."""

    @abstractmethod
    def stop(self) -> None:
        """Stop the channel cleanly."""


class ChannelBroker:
    """Holds the shared agent builder and dispatches to channels."""

    def __init__(self, controller_factory):
        self.controller_factory = controller_factory
        self.channels: dict[str, Channel] = {}

    def register(self, channel: Channel) -> None:
        self.channels[channel.name] = channel

    def new_controller(self):
        return self.controller_factory()

    def start_all(self) -> None:
        for ch in self.channels.values():
            ch.start()

    def stop_all(self) -> None:
        for ch in self.channels.values():
            ch.stop()
