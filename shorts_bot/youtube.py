from __future__ import annotations

import asyncio
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

from .errors import UploadError
from .models import ShortPlan

YOUTUBE_UPLOAD_SCOPE = "https://www.googleapis.com/auth/youtube.upload"


class YouTubeUploader:
    def __init__(self, token_file: Path, privacy_status: str = "private") -> None:
        self.token_file = token_file
        self.privacy_status = privacy_status

    async def upload(self, video_path: Path, plan: ShortPlan) -> str:
        return await asyncio.to_thread(self._upload_sync, video_path, plan)

    def _credentials(self) -> Credentials:
        try:
            credentials = Credentials.from_authorized_user_file(
                str(self.token_file), [YOUTUBE_UPLOAD_SCOPE]
            )
            if credentials.expired and credentials.refresh_token:
                credentials.refresh(Request())
                self.token_file.write_text(credentials.to_json(), encoding="utf-8")
            if not credentials.valid:
                raise UploadError("YouTube OAuth credentials are invalid; run shorts-auth again.")
            return credentials
        except UploadError:
            raise
        except Exception as exc:
            raise UploadError(f"Could not load YouTube OAuth token: {exc}") from exc

    def _upload_sync(self, video_path: Path, plan: ShortPlan) -> str:
        if not video_path.exists():
            raise UploadError(f"Rendered video does not exist: {video_path}")
        try:
            youtube = build(
                "youtube",
                "v3",
                credentials=self._credentials(),
                cache_discovery=False,
            )
            request = youtube.videos().insert(
                part="snippet,status",
                notifySubscribers=False,
                body={
                    "snippet": {
                        "title": plan.title,
                        "description": plan.description,
                        "categoryId": "22",
                    },
                    "status": {
                        "privacyStatus": self.privacy_status,
                        "selfDeclaredMadeForKids": False,
                    },
                },
                media_body=MediaFileUpload(
                    str(video_path),
                    mimetype="video/mp4",
                    chunksize=8 * 1024 * 1024,
                    resumable=True,
                ),
            )
            response = None
            while response is None:
                _, response = request.next_chunk()
            video_id = response.get("id")
            if not video_id:
                raise UploadError("YouTube accepted the request but returned no video ID.")
            return str(video_id)
        except UploadError:
            raise
        except HttpError as exc:
            detail = getattr(exc, "reason", None) or str(exc)
            raise UploadError(f"YouTube API rejected the upload: {detail}") from exc
        except Exception as exc:
            raise UploadError(f"YouTube upload failed: {exc}") from exc
