from pathlib import Path

import httpx
import pytest

from shorts_bot.instagram_dm import InstagramDirectMessenger, list_instagram_chats


class FakeTemporaryHost:
    def __init__(self) -> None:
        self.uploaded: list[tuple[Path, str]] = []
        self.deleted: list[str] = []

    async def upload(self, video_path: Path, public_id: str) -> tuple[str, str]:
        self.uploaded.append((video_path, public_id))
        return "https://cdn.example.test/video.mp4", f"{public_id}-stored"

    async def delete(self, public_id: str) -> None:
        self.deleted.append(public_id)


async def test_sends_hosted_video_to_configured_instagram_chat(tmp_path: Path) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={"recipient_id": "456", "message_id": "message-1"},
        )

    host = FakeTemporaryHost()
    video = tmp_path / "short.mp4"
    video.write_bytes(b"video")
    messenger = InstagramDirectMessenger(
        sender_id="123",
        recipient_id="456",
        access_token="secret-token",
        temporary_host=host,
        delay_min_seconds=0,
        delay_max_seconds=0,
        transport=httpx.MockTransport(handler),
    )

    message_id = await messenger.send_video(video, "soul_exter/dm/job/clip-001")

    assert message_id == "message-1"
    assert host.uploaded == [(video, "soul_exter/dm/job/clip-001")]
    assert host.deleted == ["soul_exter/dm/job/clip-001-stored"]
    assert len(requests) == 1
    request = requests[0]
    assert request.url == "https://graph.instagram.com/v26.0/123/messages"
    assert request.headers["authorization"] == "Bearer secret-token"
    assert b'"id":"456"' in request.content
    assert b'"type":"video"' in request.content
    assert b"https://cdn.example.test/video.mp4" in request.content


async def test_lists_recipient_igsids_and_excludes_sender() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v26.0/me/conversations"
        assert request.headers["authorization"] == "Bearer secret-token"
        return httpx.Response(
            200,
            json={
                "data": [
                    {
                        "id": "conversation-1",
                        "participants": {
                            "data": [
                                {"id": "123", "username": "splitzz.isodope"},
                                {"id": "456", "username": "destination"},
                            ]
                        },
                    }
                ]
            },
        )

    chats = await list_instagram_chats(
        "secret-token",
        "v26.0",
        sender_id="123",
        transport=httpx.MockTransport(handler),
    )

    assert chats == [
        {
            "conversation_id": "conversation-1",
            "recipient_id": "456",
            "username": "destination",
        }
    ]


async def test_waits_between_confirmed_instagram_messages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    delays: list[float] = []

    async def fake_sleep(delay: float) -> None:
        delays.append(delay)

    monkeypatch.setattr("shorts_bot.instagram_dm.random.uniform", lambda start, end: 3.5)
    monkeypatch.setattr("shorts_bot.instagram_dm.asyncio.sleep", fake_sleep)
    messenger = InstagramDirectMessenger(
        sender_id="123",
        recipient_id="456",
        access_token="token",
        temporary_host=FakeTemporaryHost(),
        delay_min_seconds=3,
        delay_max_seconds=4,
    )

    await messenger.wait_before_next_message()

    assert delays == [3.5]
