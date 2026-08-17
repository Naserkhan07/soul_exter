from __future__ import annotations

import argparse
import asyncio
import logging
import random
from pathlib import Path
from typing import Any

import httpx

from .enhancer import TemporaryVideoHost
from .errors import ConfigurationError, DirectMessageError

logger = logging.getLogger(__name__)


class InstagramDirectMessenger:
    """Send generated MP4 files to one existing Instagram conversation."""

    def __init__(
        self,
        sender_id: str,
        recipient_id: str,
        access_token: str,
        temporary_host: TemporaryVideoHost,
        recipient_username: str = "",
        api_version: str = "v26.0",
        delay_min_seconds: int = 3,
        delay_max_seconds: int = 4,
        retry_attempts: int = 4,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.sender_id = sender_id
        self.recipient_id = recipient_id
        self.recipient_username = recipient_username.strip().lstrip("@")
        self.access_token = access_token
        self.temporary_host = temporary_host
        self.api_version = api_version
        self.delay_min_seconds = delay_min_seconds
        self.delay_max_seconds = delay_max_seconds
        self.retry_attempts = max(1, retry_attempts)
        self.transport = transport
        self.endpoint = f"https://graph.instagram.com/{self.api_version}/me/messages"

    async def send_video(self, video_path: Path, public_id: str) -> str:
        if not video_path.exists():
            raise DirectMessageError(f"Instagram DM video does not exist: {video_path}")

        await self._resolve_recipient_id()
        hosted_url = ""
        hosted_id = public_id
        try:
            hosted_url, hosted_id = await self.temporary_host.upload(video_path, public_id)
            return await self._send_hosted_video(hosted_url)
        except DirectMessageError:
            raise
        except Exception as exc:
            raise DirectMessageError(f"Instagram DM delivery failed: {exc}") from exc
        finally:
            if hosted_url:
                await self.temporary_host.delete(hosted_id)

    async def _resolve_recipient_id(self) -> str:
        if self.recipient_id:
            return self.recipient_id
        if not self.recipient_username:
            raise DirectMessageError("No Instagram DM recipient was configured.")
        chats = await list_instagram_chats(
            self.access_token,
            self.api_version,
            sender_id=self.sender_id,
            transport=self.transport,
        )
        matches = [
            chat
            for chat in chats
            if chat["username"].casefold() == self.recipient_username.casefold()
        ]
        if not matches:
            raise DirectMessageError(
                f"No eligible Instagram chat was found for @{self.recipient_username}. "
                "That account must send the Professional account a new message first."
            )
        recipient_ids = {chat["recipient_id"] for chat in matches}
        if len(recipient_ids) != 1:
            raise DirectMessageError(
                f"Instagram returned multiple recipient IDs for @{self.recipient_username}; "
                "configure INSTAGRAM_DM_RECIPIENT_ID explicitly."
            )
        self.recipient_id = recipient_ids.pop()
        return self.recipient_id

    async def wait_before_next_message(self) -> None:
        delay = random.uniform(self.delay_min_seconds, self.delay_max_seconds)
        if delay > 0:
            await asyncio.sleep(delay)

    async def _send_hosted_video(self, hosted_url: str) -> str:
        timeout = httpx.Timeout(120, read=300)
        async with httpx.AsyncClient(timeout=timeout, transport=self.transport) as client:
            for attempt in range(1, self.retry_attempts + 1):
                try:
                    response = await client.post(
                        self.endpoint,
                        headers={
                            "Authorization": f"Bearer {self.access_token}",
                            "Content-Type": "application/json",
                        },
                        json={
                            "recipient": {"id": self.recipient_id},
                            "message": {
                                "attachment": {
                                    "type": "video",
                                    "payload": {"url": hosted_url},
                                }
                            },
                        },
                    )
                    if response.is_success:
                        payload = self._json(response)
                        message_id = str(payload.get("message_id") or "")
                        returned_recipient = str(payload.get("recipient_id") or "")
                        if not message_id:
                            raise DirectMessageError(
                                "Instagram accepted the DM request but returned no message ID."
                            )
                        if returned_recipient and returned_recipient != self.recipient_id:
                            raise DirectMessageError(
                                "Instagram returned a different DM recipient than configured."
                            )
                        return message_id

                    detail = self._error_detail(response)
                    if response.status_code < 500 or attempt == self.retry_attempts:
                        raise DirectMessageError(f"Instagram DM API rejected the video: {detail}")
                except DirectMessageError:
                    raise
                except httpx.HTTPError as exc:
                    if attempt == self.retry_attempts:
                        raise DirectMessageError(
                            "Instagram DM network request failed after retries."
                        ) from exc

                delay = min(30, 2 ** (attempt - 1))
                logger.warning(
                    "Instagram DM returned a temporary server/network error; retrying in "
                    "%s seconds (%s/%s)",
                    delay,
                    attempt + 1,
                    self.retry_attempts,
                )
                await asyncio.sleep(delay)

        raise DirectMessageError("Instagram DM delivery ended without a result.")

    @staticmethod
    def _json(response: httpx.Response) -> dict[str, Any]:
        try:
            payload = response.json()
            return payload if isinstance(payload, dict) else {}
        except ValueError as exc:
            raise DirectMessageError("Instagram DM API returned invalid JSON.") from exc

    @classmethod
    def _error_detail(cls, response: httpx.Response) -> str:
        fallback = f"HTTP {response.status_code}"
        try:
            payload = response.json()
        except ValueError:
            body = response.text.strip()
            return f"{fallback}: {body[:500]}" if body else fallback
        if not isinstance(payload, dict):
            return fallback
        error = payload.get("error")
        if isinstance(error, dict):
            return str(error.get("error_user_msg") or error.get("message") or fallback)
        return str(payload.get("message") or fallback)


async def list_instagram_chats(
    access_token: str,
    api_version: str,
    sender_id: str = "",
    transport: httpx.AsyncBaseTransport | None = None,
) -> list[dict[str, str]]:
    """Return existing conversations and participant IGSIDs without exposing the token."""
    url = f"https://graph.instagram.com/{api_version}/me/conversations"
    timeout = httpx.Timeout(60, read=120)
    async with httpx.AsyncClient(timeout=timeout, transport=transport) as client:
        try:
            response = await client.get(
                url,
                headers={"Authorization": f"Bearer {access_token}"},
                params={
                    "platform": "instagram",
                    "fields": "id,participants",
                    "limit": "50",
                },
            )
        except httpx.HTTPError as exc:
            raise DirectMessageError("Could not request the Instagram chat list.") from exc
    if not response.is_success:
        detail = InstagramDirectMessenger._error_detail(response)
        raise DirectMessageError(f"Could not list Instagram chats: {detail}")
    payload = InstagramDirectMessenger._json(response)
    conversations = payload.get("data", [])
    results: list[dict[str, str]] = []
    if not isinstance(conversations, list):
        return results
    for conversation in conversations:
        if not isinstance(conversation, dict):
            continue
        conversation_id = str(conversation.get("id") or "")
        participant_block = conversation.get("participants", {})
        participants = (
            participant_block.get("data", []) if isinstance(participant_block, dict) else []
        )
        if not isinstance(participants, list):
            continue
        for participant in participants:
            if not isinstance(participant, dict):
                continue
            participant_id = str(participant.get("id") or "")
            if participant_id and participant_id != sender_id:
                results.append(
                    {
                        "conversation_id": conversation_id,
                        "recipient_id": participant_id,
                        "username": str(participant.get("username") or "unknown"),
                    }
                )
    return results


def main() -> None:
    parser = argparse.ArgumentParser(
        description="List existing Instagram chats and their recipient IGSIDs."
    )
    parser.parse_args()

    from .config import Settings

    try:
        settings = Settings.from_env()
        if settings.instagram_dm_recipient_id:
            print(
                "Instagram DM recipient is configured from a captured scoped ID; "
                "chat lookup is no longer required."
            )
            return
        if not settings.instagram_dm_access_token:
            raise ConfigurationError("Add INSTAGRAM_DM_ACCESS_TOKEN to .env before listing chats.")
        chats = asyncio.run(
            list_instagram_chats(
                settings.instagram_dm_access_token,
                settings.instagram_graph_api_version,
                sender_id=settings.instagram_dm_sender_id,
            )
        )
    except (ConfigurationError, DirectMessageError) as exc:
        parser.error(str(exc))
        return

    if not chats:
        print(
            "No eligible chats were returned. Send splitzz.isodope a new message from the "
            "destination account, then run this command again."
        )
        return
    print("Eligible Instagram chats:")
    for chat in chats:
        print(
            f"- @{chat['username']}: recipient_id={chat['recipient_id']} "
            f"conversation_id={chat['conversation_id']}"
        )


if __name__ == "__main__":
    main()
