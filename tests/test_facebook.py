from pathlib import Path

import httpx
import pytest

from shorts_bot.errors import UploadLimitError
from shorts_bot.facebook import FacebookReelUploader
from shorts_bot.models import ShortPlan


async def test_facebook_reel_upload_and_publish_flow(tmp_path: Path) -> None:
    calls: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        if request.method == "GET" and request.url.path == "/v26.0/page-123":
            assert request.url.params["fields"] == "id,name"
            return httpx.Response(200, json={"id": "page-123", "name": "Splitzz"})
        if request.url.path == "/v26.0/page-123/video_reels":
            if b"upload_phase=start" in request.content:
                return httpx.Response(
                    200,
                    json={
                        "video_id": "video-456",
                        "upload_url": "https://rupload.facebook.com/video-upload/v26.0/video-456",
                    },
                )
            assert b"upload_phase=finish" in request.content
            assert b"video_state=PUBLISHED" in request.content
            return httpx.Response(200, json={"success": True})
        if request.url.host == "rupload.facebook.com":
            assert request.headers["authorization"] == "OAuth page-token"
            assert request.content == b"video"
            return httpx.Response(200, json={"success": True})
        if request.url.path == "/v26.0/video-456":
            return httpx.Response(
                200,
                json={
                    "status": {
                        "video_status": "ready",
                        "publishing_phase": {"status": "complete"},
                    }
                },
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    video_path = tmp_path / "short.mp4"
    video_path.write_bytes(b"video")
    uploader = FacebookReelUploader(
        page_id="page-123",
        access_token="page-token",
        poll_interval_seconds=1,
        transport=httpx.MockTransport(handler),
    )
    plan = ShortPlan(0, 30, "Title #Shorts", "Description", "Caption")

    assert await uploader.check_connection() == "Splitzz"
    video_id, url = await uploader.upload(video_path, plan)

    assert video_id == "video-456"
    assert url == "https://www.facebook.com/reel/video-456"
    assert calls == [
        ("GET", "/v26.0/page-123"),
        ("POST", "/v26.0/page-123/video_reels"),
        ("POST", "/video-upload/v26.0/video-456"),
        ("POST", "/v26.0/page-123/video_reels"),
        ("GET", "/v26.0/video-456"),
    ]


def test_detects_facebook_reel_publishing_limit() -> None:
    response = httpx.Response(
        400,
        request=httpx.Request("POST", "https://graph.facebook.com/video_reels"),
        json={"error": {"code": 4, "message": "Application request limit reached"}},
    )

    with pytest.raises(UploadLimitError, match="Facebook upload limit reached"):
        FacebookReelUploader._raise_for_meta_error(response, "Facebook Reel publishing")
