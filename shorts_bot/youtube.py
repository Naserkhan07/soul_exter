from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

from .errors import UploadError, UploadLimitError
from .models import ShortPlan

logger = logging.getLogger(__name__)

YOUTUBE_UPLOAD_SCOPE = "https://www.googleapis.com/auth/youtube.upload"
YOUTUBE_READONLY_SCOPE = "https://www.googleapis.com/auth/youtube.readonly"
YOUTUBE_SCOPES = [YOUTUBE_UPLOAD_SCOPE, YOUTUBE_READONLY_SCOPE]
YOUTUBE_TITLE_MAX_CHARS = 100
YOUTUBE_DESCRIPTION_MAX_CHARS = 5000


def _shorts_title(title: str) -> str:
    cleaned = " ".join(title.split()) or "YouTube Short"
    if "#shorts" in cleaned.casefold():
        return cleaned[:YOUTUBE_TITLE_MAX_CHARS].rstrip()
    suffix = " #Shorts"
    base = cleaned[: YOUTUBE_TITLE_MAX_CHARS - len(suffix)].rstrip(" -|:")
    return f"{base}{suffix}"


def _shorts_description(description: str) -> str:
    cleaned = description.strip()
    if "#shorts" in cleaned.casefold():
        return cleaned[:YOUTUBE_DESCRIPTION_MAX_CHARS].rstrip()
    suffix = "\n\n#Shorts"
    base = cleaned[: YOUTUBE_DESCRIPTION_MAX_CHARS - len(suffix)].rstrip()
    return f"{base}{suffix}" if base else "#Shorts"


class YouTubeUploader:
    def __init__(
        self,
        token_file: Path,
        privacy_status: str = "public",
        expected_channel_id: str = "",
    ) -> None:
        self.token_file = token_file
        self.privacy_status = privacy_status
        self.expected_channel_id = expected_channel_id

    async def upload(
        self,
        video_path: Path,
        plan: ShortPlan,
        thumbnail_path: Path | None = None,
    ) -> str:
        return await asyncio.to_thread(self._upload_sync, video_path, plan, thumbnail_path)

    def _credentials(self) -> Credentials:
        try:
            credentials = Credentials.from_authorized_user_file(
                str(self.token_file), YOUTUBE_SCOPES
            )
            if not credentials.has_scopes(YOUTUBE_SCOPES):
                raise UploadError(
                    "YouTube OAuth token is missing required channel verification scope; "
                    "delete it and run shorts-auth again."
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

    def _upload_sync(
        self,
        video_path: Path,
        plan: ShortPlan,
        thumbnail_path: Path | None = None,
    ) -> str:
        if not video_path.exists():
            raise UploadError(f"Rendered video does not exist: {video_path}")
        try:
            youtube = build(
                "youtube",
                "v3",
                credentials=self._credentials(),
                cache_discovery=False,
            )
            self._verify_channel(youtube)
            request = youtube.videos().insert(
                part="snippet,status",
                notifySubscribers=False,
                body={
                    "snippet": {
                        "title": _shorts_title(plan.title),
                        "description": _shorts_description(plan.description),
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
            if thumbnail_path and thumbnail_path.exists():
                self._try_set_thumbnail(youtube, str(video_id), thumbnail_path)
            return str(video_id)
        except UploadLimitError:
            raise
        except UploadError:
            raise
        except HttpError as exc:
            detail = _youtube_http_error_detail(exc)
            if _is_youtube_upload_limit(exc, detail):
                raise UploadLimitError("YouTube", detail) from exc
            raise UploadError(f"YouTube API rejected the upload: {detail}") from exc
        except Exception as exc:
            raise UploadError(f"YouTube upload failed: {exc}") from exc

    @staticmethod
    def _try_set_thumbnail(youtube: object, video_id: str, thumbnail_path: Path) -> None:
        try:
            youtube.thumbnails().set(  # type: ignore[attr-defined]
                videoId=video_id,
                media_body=MediaFileUpload(
                    str(thumbnail_path),
                    mimetype="image/jpeg",
                    resumable=False,
                ),
            ).execute()
        except HttpError as exc:
            logger.warning("YouTube did not accept the custom thumbnail: %s", exc.reason)

    def _verify_channel(self, youtube: object) -> None:
        if not self.expected_channel_id:
            return
        response = youtube.channels().list(part="id", mine=True).execute()  # type: ignore[attr-defined]
        authorized_ids = {str(item.get("id")) for item in response.get("items", [])}
        if self.expected_channel_id not in authorized_ids:
            found = ", ".join(sorted(authorized_ids)) or "no channel"
            raise UploadError(
                f"OAuth is authorized for {found}, but channels.toml specifies "
                f"{self.expected_channel_id}. Run shorts-auth with the correct account."
            )


def _youtube_http_error_payload(exc: HttpError) -> dict[str, Any]:
    try:
        content = exc.content.decode("utf-8") if isinstance(exc.content, bytes) else exc.content
        payload = json.loads(content or "{}")
        return payload if isinstance(payload, dict) else {}
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError):
        return {}


def _youtube_http_error_detail(exc: HttpError) -> str:
    payload = _youtube_http_error_payload(exc)
    error = payload.get("error", {})
    if isinstance(error, dict):
        errors = error.get("errors", [])
        if isinstance(errors, list) and errors and isinstance(errors[0], dict):
            return str(errors[0].get("message") or errors[0].get("reason") or exc.reason)
        return str(error.get("message") or exc.reason)
    return str(getattr(exc, "reason", None) or exc)


def _is_youtube_upload_limit(exc: HttpError, detail: str) -> bool:
    payload = _youtube_http_error_payload(exc)
    text = f"{detail} {json.dumps(payload)}".casefold()
    markers = (
        "quotaexceeded",
        "dailylimitexceeded",
        "uploadlimitexceeded",
        "uploadratelimitexceeded",
        "daily upload limit",
        "upload limit",
        "quota exceeded",
    )
    return any(marker in text for marker in markers)
