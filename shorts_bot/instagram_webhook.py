from __future__ import annotations

import argparse
import json
import os
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from dotenv import load_dotenv

from .config import Settings

WEBHOOK_PATH = "/instagram-webhook"


def set_dotenv_value(path: Path, name: str, value: str) -> None:
    """Set one dotenv value, removing duplicate definitions without exposing secrets."""
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    prefix = f"{name}="
    updated: list[str] = []
    replaced = False
    for line in lines:
        if line.strip().startswith(prefix):
            if not replaced:
                updated.append(f"{name}={value}")
                replaced = True
            continue
        updated.append(line)
    if not replaced:
        if updated and updated[-1]:
            updated.append("")
        updated.append(f"{name}={value}")
    path.write_text("\n".join(updated) + "\n", encoding="utf-8")


def incoming_sender_ids(payload: Any, expected_business_id: str = "") -> list[str]:
    """Extract customer IGSIDs from Instagram messaging webhook notifications."""
    if not isinstance(payload, dict) or payload.get("object") != "instagram":
        return []
    found: list[str] = []
    entries = payload.get("entry", [])
    if not isinstance(entries, list):
        return found
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        entry_id = str(entry.get("id") or "")
        messaging_items = entry.get("messaging", [])
        if not isinstance(messaging_items, list):
            continue
        for item in messaging_items:
            if not isinstance(item, dict):
                continue
            sender = item.get("sender", {})
            recipient = item.get("recipient", {})
            sender_id = str(sender.get("id") or "") if isinstance(sender, dict) else ""
            recipient_id = str(recipient.get("id") or "") if isinstance(recipient, dict) else ""
            message = item.get("message", {})
            is_echo = isinstance(message, dict) and bool(message.get("is_echo"))
            if not sender_id or is_echo:
                continue
            business_id = recipient_id or entry_id
            if expected_business_id and business_id != expected_business_id:
                continue
            if sender_id not in {business_id, expected_business_id} and sender_id not in found:
                found.append(sender_id)
    return found


class CaptureState:
    def __init__(
        self,
        verify_token: str,
        env_path: Path,
        expected_business_id: str,
    ) -> None:
        self.verify_token = verify_token
        self.env_path = env_path
        self.expected_business_id = expected_business_id
        self.captured_id = ""


def build_handler(state: CaptureState) -> type[BaseHTTPRequestHandler]:
    class InstagramWebhookHandler(BaseHTTPRequestHandler):
        server: ThreadingHTTPServer

        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            if parsed.path != WEBHOOK_PATH:
                self._send(404, "Not found")
                return
            params = parse_qs(parsed.query)
            mode = (params.get("hub.mode") or [""])[0]
            token = (params.get("hub.verify_token") or [""])[0]
            challenge = (params.get("hub.challenge") or [""])[0]
            if mode == "subscribe" and secrets.compare_digest(token, state.verify_token):
                self._send(200, challenge)
                print("Meta verified the local Instagram webhook.", flush=True)
                return
            self._send(403, "Verification failed")

        def do_POST(self) -> None:  # noqa: N802
            if urlparse(self.path).path != WEBHOOK_PATH:
                self._send(404, "Not found")
                return
            try:
                content_length = min(int(self.headers.get("Content-Length", "0")), 2_000_000)
                payload = json.loads(self.rfile.read(content_length) or b"{}")
            except (ValueError, json.JSONDecodeError):
                self._send(400, "Invalid JSON")
                return

            sender_ids = incoming_sender_ids(payload, state.expected_business_id)
            self._send(200, "EVENT_RECEIVED")
            if not sender_ids or state.captured_id:
                return

            state.captured_id = sender_ids[0]
            set_dotenv_value(
                state.env_path,
                "INSTAGRAM_DM_RECIPIENT_ID",
                state.captured_id,
            )
            print(
                "Captured the destination chat and saved INSTAGRAM_DM_RECIPIENT_ID to .env.",
                flush=True,
            )
            print("The webhook capture server will now stop.", flush=True)
            threading.Thread(target=self.server.shutdown, daemon=True).start()

        def log_message(self, format: str, *args: object) -> None:
            return

        def _send(self, status: int, body: str) -> None:
            encoded = body.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

    return InstagramWebhookHandler


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Capture one Instagram chat recipient ID through a temporary local webhook."
    )
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    args = parser.parse_args()

    load_dotenv(args.env_file, override=False)
    settings = Settings.from_env(args.env_file)
    verify_token = os.getenv("INSTAGRAM_WEBHOOK_VERIFY_TOKEN", "").strip()
    if not verify_token:
        verify_token = secrets.token_urlsafe(32)
        set_dotenv_value(args.env_file, "INSTAGRAM_WEBHOOK_VERIFY_TOKEN", verify_token)

    state = CaptureState(
        verify_token=verify_token,
        env_path=args.env_file,
        expected_business_id=settings.instagram_dm_sender_id,
    )
    server = ThreadingHTTPServer((args.host, args.port), build_handler(state))
    server.daemon_threads = True

    print(f"Instagram webhook capture server listening on port {args.port}.", flush=True)
    print(f"Callback path: {WEBHOOK_PATH}", flush=True)
    print(f"Verify token: {verify_token}", flush=True)
    print(
        "Keep this terminal open. Start a Cloudflare tunnel in a second terminal, configure "
        "Meta's callback URL, then send one new DM from the destination account.",
        flush=True,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("Webhook capture stopped.", flush=True)
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
