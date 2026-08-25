import json
from pathlib import Path

import httpx

from shorts_bot.enhancer import APIMarketVideoEnhancer


class FakeTemporaryHost:
    def __init__(self) -> None:
        self.deleted: list[str] = []

    async def upload(self, video_path: Path, public_id: str) -> tuple[str, str]:
        assert video_path.read_bytes() == b"input-video"
        return "https://temporary.example/input.mp4", public_id

    async def delete(self, public_id: str) -> None:
        self.deleted.append(public_id)


async def test_api_market_prediction_flow_and_temporary_cleanup(tmp_path: Path) -> None:
    calls: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        if request.url.host == "prod.api.market":
            assert request.headers["x-magicapi-key"] == "private-key"
        if request.method == "POST":
            payload = json.loads(request.content)
            assert payload["input"]["model"] == "RealESRGAN_x4plus"
            assert payload["input"]["resolution"] == "FHD"
            assert payload["input"]["video_path"] == "https://temporary.example/input.mp4"
            return httpx.Response(201, json={"id": "prediction-1", "status": "starting"})
        if request.url.host == "output.example":
            return httpx.Response(200, content=b"enhanced-video")
        return httpx.Response(
            200,
            json={
                "id": "prediction-1",
                "status": "succeeded",
                "output": "https://output.example/enhanced.mp4",
            },
        )

    source = tmp_path / "short.mp4"
    source.write_bytes(b"input-video")
    output = tmp_path / "short-enhanced.mp4"
    temporary_host = FakeTemporaryHost()
    enhancer = APIMarketVideoEnhancer(
        api_key="private-key",
        temporary_host=temporary_host,
        base_url="https://prod.api.market/api/v1/upscaler",
        version="version-id",
        timeout_seconds=60,
        poll_interval_seconds=0,
        transport=httpx.MockTransport(handler),
    )

    result = await enhancer.enhance(source, output, "job/clip-001")

    assert result.read_bytes() == b"enhanced-video"
    assert temporary_host.deleted == ["job/clip-001"]
    assert calls == [
        ("POST", "/api/v1/upscaler/predictions"),
        ("GET", "/api/v1/upscaler/predictions/prediction-1"),
        ("GET", "/enhanced.mp4"),
    ]
