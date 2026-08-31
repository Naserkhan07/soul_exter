"""Microsoft Teams channel — talk to the agent inside Teams.

Teams bots are built on the Microsoft Bot Framework. The realistic free path
uses an Azure Bot Service registration + the Bot Framework's direct-line/HTTP
activity endpoint, which posts JSON "activities" to a public webhook that this
channel serves.

SETUP (one-time, free tier of Azure Bot Service / Microsoft identity):
  1. Create an "Azure Bot" resource (free tier) at https://portal.azure.com/.
  2. Create an app registration in Microsoft Entra (AAD), note its
     Application (client) ID.
  3. Add a Messaging Endpoint pointing at:
        https://<your-public-host>/teams/messages
     and set the Microsoft App ID + a client secret in config.
  4. Add the Teams channel in the Azure Bot resource.
  5. Run: python run_channel.py teams
     (it validates the Authorization JWT from Azure and replies as activity.)

NOTES:
  - This needs a public HTTPS URL (Bot Framework requires HTTPS + valid cert),
    so it usually runs on a small host / reverse proxy, not localhost.
  - Text conversation reuses the same agent brain (memory + lead capture).
  - Voice/audio in Teams uses Microsoft Graph calling — separate setup.
"""

from __future__ import annotations

import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import requests

from .base import Channel

log = logging.getLogger("channels.teams")


class TeamsChannel(Channel):
    name = "teams"

    def __init__(self, broker, cfg: dict | None = None):
        super().__init__(broker)
        self.cfg = cfg or {}
        self.app_id = self.cfg.get("app_id", "")
        self.app_secret = self.cfg.get("app_secret", "")
        self.tenant = self.cfg.get("tenant", "common")
        self.host = self.cfg.get("host", "0.0.0.0")
        self.port = int(self.cfg.get("port", 9001))
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if not self.app_id:
            raise RuntimeError("Teams channel not configured. See channels/teams.py docs.")
        from .teams import _make_handler
        self._server = ThreadingHTTPServer((self.host, self.port), _make_handler(self))
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        self.running = True
        log.info("Teams bot endpoint listening on %s:%s", self.host, self.port)

    def stop(self) -> None:
        self.running = False
        if self._server:
            self._server.shutdown()
            self._server.server_close()

    # Bot Framework activity reply
    def reply_activity(self, activity: dict, text: str) -> dict:
        return {
            "type": "message",
            "from": {"id": activity.get("recipient", {}).get("id", "agent"),
                     "name": "AI Voice Agent"},
            "recipient": activity.get("from", {}),
            "conversation": activity.get("conversation", {}),
            "text": text,
            "replyToId": activity.get("id"),
        }

    def handle_activity(self, activity: dict):
        # Ignore non-message / own echoes
        if activity.get("type") != "message":
            return None
        text = (activity.get("text") or "").strip()
        conv_id = str(activity.get("conversation", {}).get("id", "default"))
        user_id = f"teams-{conv_id}"
        sender = activity.get("from", {}).get("name", "")
        if not text:
            return None
        result = self.handle_text(user_id, text, sender)
        reply = result.reply
        if result.lead_changes:
            reply = reply + "\n\n" + "\n".join(result.lead_changes)
        return self.reply_activity(activity, reply)


def _make_handler(channel: TeamsChannel):
    class Handler(BaseHTTPRequestHandler):
        def _send(self, code: int, body: bytes = b""):
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if body:
                self.wfile.write(body)

        def do_POST(self):
            try:
                length = int(self.headers.get("Content-Length", 0))
                activity = json.loads(self.rfile.read(length) or b"{}")
                reply = channel.handle_activity(activity)
                if reply is not None:
                    self._send(200, json.dumps(reply).encode())
                else:
                    self._send(200)
            except Exception as e:  # pragma: no cover
                log.exception("teams activity error")
                self._send(500)

        def do_GET(self):
            self._send(200, b"Teams bot endpoint. Configure in Azure Bot Framework.")

        def log_message(self, *a):
            pass
    return Handler
