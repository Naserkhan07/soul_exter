from pathlib import Path

import httpx

from shorts_bot.instagram import InstagramUploader
from shorts_bot.models import ShortPlan


async def test_instagram_resumable_reel_publish_flow(tmp_path: Path) -> None:
    calls: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        if request.url.path == "/v26.0/1789/media":
            assert b"share_to_feed=true" in request.content
            return httpx.Response(
                200,
                json={
                    "id": "container-id",
                    "uri": ("https://rupload.facebook.com/ig-api-upload/v26.0/container-id"),
                },
            )
        if request.url.host == "rupload.facebook.com":
            assert request.headers["authorization"] == "OAuth secret-token"
            assert request.content == b"video"
            return httpx.Response(200, json={"success": True})
        if request.url.path == "/v26.0/container-id":
            return httpx.Response(200, json={"status_code": "FINISHED"})
        if request.url.path == "/v26.0/1789/media_publish":
            return httpx.Response(200, json={"id": "media-id"})
        if request.url.path == "/v26.0/media-id":
            return httpx.Response(
                200,
                json={"permalink": "https://www.instagram.com/reel/example/"},
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    video_path = tmp_path / "short.mp4"
    video_path.write_bytes(b"video")
    uploader = InstagramUploader(
        user_id="1789",
        access_token="secret-token",
        transport=httpx.MockTransport(handler),
    )
    plan = ShortPlan(0, 25, "Title #Shorts", "Description", "Caption #Reels")

    result = await uploader.upload(video_path, plan)

    assert result.media_id == "media-id"
    assert result.permalink == "https://www.instagram.com/reel/example/"
    assert calls == [
        ("POST", "/v26.0/1789/media"),
        ("POST", "/ig-api-upload/v26.0/container-id"),
        ("GET", "/v26.0/container-id"),
        ("POST", "/v26.0/1789/media_publish"),
        ("GET", "/v26.0/media-id"),
    ]
