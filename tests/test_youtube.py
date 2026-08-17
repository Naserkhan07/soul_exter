import json
from pathlib import Path

import pytest
from googleapiclient.errors import HttpError
from httplib2 import Response

from shorts_bot.errors import UploadError
from shorts_bot.youtube import YouTubeUploader, _is_youtube_upload_limit


class FakeChannelRequest:
    def __init__(self, channel_ids: list[str]) -> None:
        self.channel_ids = channel_ids

    def list(self, **kwargs):  # noqa: ANN003, ANN201
        assert kwargs == {"part": "id", "mine": True}
        return self

    def execute(self):  # noqa: ANN201
        return {"items": [{"id": channel_id} for channel_id in self.channel_ids]}


class FakeYouTube:
    def __init__(self, channel_ids: list[str]) -> None:
        self.request = FakeChannelRequest(channel_ids)

    def channels(self) -> FakeChannelRequest:
        return self.request


def test_verifies_oauth_channel_matches_configuration() -> None:
    uploader = YouTubeUploader(Path("token.json"), expected_channel_id="UC-correct")

    uploader._verify_channel(FakeYouTube(["UC-correct"]))

    with pytest.raises(UploadError, match="channels.toml specifies UC-correct"):
        uploader._verify_channel(FakeYouTube(["UC-wrong"]))


def test_detects_youtube_daily_upload_limit_reason() -> None:
    content = json.dumps(
        {
            "error": {
                "errors": [
                    {
                        "reason": "uploadLimitExceeded",
                        "message": "The user has exceeded the number of videos they may upload.",
                    }
                ]
            }
        }
    ).encode()
    error = HttpError(Response({"status": "403", "reason": "Forbidden"}), content)

    assert _is_youtube_upload_limit(error, "uploadLimitExceeded")
