"""WhatsApp channel — talk to the agent on WhatsApp.

Uses the official WhatsApp Business Cloud API (Meta). Setup requires a
Meta-for-Developers account and a verified WhatsApp Business number, then a
webhook that this class exposes via a small HTTP server.

SETUP (once):
  1. Create an app at https://developers.facebook.com/ (Business type).
  2. Add the "WhatsApp" product, connect a WhatsApp Business number and a test
     number, and get a permanent access token.
  3. In config `channels.whatsapp` set:
       verify_token   : any secret string you choose
       access_token   : your permanent token
       phone_number_id: the business number id
       port           : a public port (e.g. 9000) reachable by Meta's webhook
  4. Run: python run_channel.py whatsapp
  5. Configure the webhook URL (https://<your-public-host>/whatsapp/webhook)
     in the Meta app with the same verify_token.

Meta sends POST /whatsapp/webhook with message webhooks; the agent replies via
the Graph API send endpoint.
"""

from __future__ import annotations

import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib import request as ur

import requests

from .base import Channel

log = logging.getLogger("channels.whatsapp")

GRAPH = "https://graph.facebook.com/v19.0/{phone_id}/messages"


class WhatsAppChannel(Channel):
    name = "whatsapp"

    def __init__(self, broker, cfg: dict | None = None):
        super().__init__(broker)
        import os
        self.cfg = cfg or {}
        self.verify_token = self.cfg.get("verify_token", "")
        self.access_token = self.cfg.get("access_token", "") or \
            os.environ.get("WHATSAPP_ACCESS_TOKEN", "")
        self.phone_number_id = self.cfg.get("phone_number_id", "")
        self.host = self.cfg.get("host", "0.0.0.0")
        self.port = int(self.cfg.get("port", 9000))
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    # ---- webhook server ----
    def start(self) -> None:
        if not (self.verify_token and self.access_token and self.phone_number_id):
            raise RuntimeError(
                "WhatsApp channel not configured. See channels/whatsapp.py docs.")
        from .whatsapp import _make_handler
        self._server = ThreadingHTTPServer((self.host, self.port),
                                           _make_handler(self))
        self._thread = threading.Thread(target=self._server.serve_forever,
                                        daemon=True)
        self._thread.start()
        self.running = True
        log.info("WhatsApp webhook listening on %s:%s", self.host, self.port)

    def stop(self) -> None:
        self.running = False
        if self._server:
            self._server.shutdown()
            self._server.server_close()

    def verify(self, query: dict) -> bool:
        return query.get("hub.mode") == "subscribe" and \
            query.get("hub.verify_token") == self.verify_token

    def send_text(self, to_number: str, text: str) -> None:
        url = GRAPH.format(phone_id=self.phone_number_id)
        headers = {"Authorization": f"Bearer {self.access_token}",
                   "Content-Type": "application/json"}
        payload = {"messaging_product": "whatsapp", "to": to_number,
                   "type": "text", "text": {"body": text}}
        requests.post(url, headers=headers, json=payload, timeout=30).raise_for_status()

    def handle_webhook(self, body: dict) -> None:
        for entry in body.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value", {})
                for m in value.get("messages", []):
                    if m.get("type") != "text":
                        continue
                    from_num = m["from"]
                    text = m["text"]["body"].strip()
                    user_id = f"wa-{from_num}"
                    try:
                        result = self.handle_text(user_id, text, from_num)
                        self.send_text(from_num, result.reply)
                    except Exception as e:  # pragma: no cover
                        log.exception("whatsapp turn error")
                        self.send_text(from_num, f"Sorry: {e}")


def _make_handler(channel: WhatsAppChannel):
    class Handler(BaseHTTPRequestHandler):
        def _send(self, code: int, body: bytes = b"ok"):
            self.send_response(code)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if body:
                self.wfile.write(body)

        def do_GET(self):  # Meta verification handshake
            import urllib.parse
            q = urllib.parse.parse_qs(self.path.split("?", 1)[1]) if "?" in self.path else {}
            flat = {k: v[0] for k, v in q.items()}
            if channel.verify(flat):
                self._send(200, flat.get("hub.challenge", "ok").encode())
            else:
                self._send(403, b"forbidden")

        def do_POST(self):
            if self.path == "/whatsapp/webhook":
                try:
                    length = int(self.headers.get("Content-Length", 0))
                    body = json.loads(self.rfile.read(length) or b"{}")
                    channel.handle_webhook(body)
                    self._send(200, b"ok")
                except Exception as e:  # pragma: no cover
                    log.exception("whatsapp webhook error")
                    self._send(500, b"error")
            else:
                self._send(404)

        def log_message(self, *a):  # quiet
            pass
    return Handler
