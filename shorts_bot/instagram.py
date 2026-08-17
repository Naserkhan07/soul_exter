from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import httpx

from .errors import UploadError, UploadLimitError
from .models import InstagramUploadResult, ShortPlan


class InstagramUploader:
    """Publish local MP4 files as Reels through Meta's resumable Graph API flow."""

    def __init__(
        self,
        user_id: str,
        access_token: str,
        api_version: str = "v26.0",
        poll_interval_seconds: int = 5,
        processing_timeout_seconds: int = 600,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.user_id = user_id
        self.access_token = access_token
        self.api_version = api_version
        self.poll_interval_seconds = poll_interval_seconds
        self.processing_timeout_seconds = processing_timeout_seconds
        self.transport = transport
        self.graph_base = f"https://graph.facebook.com/{api_version}"

    async def upload(self, video_path: Path, plan: ShortPlan) -> InstagramUploadResult:
        if not video_path.exists():
            raise UploadError(f"Rendered video does not exist: {video_path}")

        timeout = httpx.Timeout(120, read=900)
        async with httpx.AsyncClient(timeout=timeout, transport=self.transport) as client:
            container = await self._post_json(
                client,
                f"{self.graph_base}/{self.user_id}/media",
                data={
                    "media_type": "REELS",
                    "upload_type": "resumable",
                    "caption": plan.instagram_caption or plan.description[:2200],
                    "share_to_feed": "true",
                    "thumb_offset": str(int(plan.duration_seconds * 500)),
                    "access_token": self.access_token,
                },
            )
            container_id = str(container.get("id") or "")
            upload_uri = str(container.get("uri") or "")
            if not container_id or not upload_uri:
                raise UploadError("Instagram did not return a resumable upload session.")

            await self._upload_binary(client, upload_uri, video_path)
            await self._wait_until_ready(client, container_id)

            published = await self._post_json(
                client,
                f"{self.graph_base}/{self.user_id}/media_publish",
                data={
                    "creation_id": container_id,
                    "access_token": self.access_token,
                },
            )
            media_id = str(published.get("id") or "")
            if not media_id:
                raise UploadError("Instagram published the container but returned no media ID.")

            permalink = await self._get_permalink(client, media_id)
            return InstagramUploadResult(media_id=media_id, permalink=permalink)

    async def _upload_binary(
        self,
        client: httpx.AsyncClient,
        upload_uri: str,
        video_path: Path,
    ) -> None:
        file_size = video_path.stat().st_size
        try:
            with video_path.open("rb") as video_file:
                response = await client.post(
                    upload_uri,
                    headers={
                        "Authorization": f"OAuth {self.access_token}",
                        "Content-Type": "video/mp4",
                        "offset": "0",
                        "file_size": str(file_size),
                    },
                    content=video_file.read(),
                )
            self._raise_for_meta_error(response, "Instagram video upload")
        except UploadError:
            raise
        except httpx.HTTPError as exc:
            raise UploadError(f"Instagram video upload request failed: {exc}") from exc

    async def _wait_until_ready(
        self,
        client: httpx.AsyncClient,
        container_id: str,
    ) -> None:
        attempts = max(1, self.processing_timeout_seconds // self.poll_interval_seconds)
        for _ in range(attempts):
            status = await self._get_json(
                client,
                f"{self.graph_base}/{container_id}",
                params={
                    "fields": "status_code,status",
                    "access_token": self.access_token,
                },
            )
            status_code = str(status.get("status_code") or "").upper()
            if status_code == "FINISHED":
                return
            if status_code in {"ERROR", "EXPIRED"}:
                detail = str(status.get("status") or status_code)
                raise UploadError(f"Instagram could not process the Reel: {detail}")
            await asyncio.sleep(self.poll_interval_seconds)
        raise UploadError("Instagram Reel processing timed out before publishing.")

    async def _get_permalink(self, client: httpx.AsyncClient, media_id: str) -> str:
        result = await self._get_json(
            client,
            f"{self.graph_base}/{media_id}",
            params={
                "fields": "permalink",
                "access_token": self.access_token,
            },
        )
        return str(result.get("permalink") or "")

    async def _post_json(
        self,
        client: httpx.AsyncClient,
        url: str,
        data: dict[str, str],
    ) -> dict[str, Any]:
        try:
            response = await client.post(url, data=data)
            self._raise_for_meta_error(response, "Instagram Graph API")
            return response.json()
        except UploadError:
            raise
        except (httpx.HTTPError, ValueError) as exc:
            raise UploadError("Instagram Graph API network request failed.") from exc

    async def _get_json(
        self,
        client: httpx.AsyncClient,
        url: str,
        params: dict[str, str],
    ) -> dict[str, Any]:
        try:
            response = await client.get(url, params=params)
            self._raise_for_meta_error(response, "Instagram Graph API")
            return response.json()
        except UploadError:
            raise
        except (httpx.HTTPError, ValueError) as exc:
            # GET query parameters contain the access token, so never echo the request URL.
            raise UploadError("Instagram Graph API network request failed.") from exc

    @staticmethod
    def _raise_for_meta_error(response: httpx.Response, operation: str) -> None:
        if response.is_success:
            return
        detail = f"HTTP {response.status_code}"
        code = 0
        try:
            payload = response.json()
            error = payload.get("error", {})
            detail = str(error.get("error_user_msg") or error.get("message") or detail)
            code = int(error.get("code") or 0)
        except (ValueError, TypeError, AttributeError):
            pass
        normalized = detail.casefold()
        limit_markers = (
            "publishing limit",
            "content publishing limit",
            "rate limit",
            "too many",
            "quota",
            "limit reached",
        )
        if any(marker in normalized for marker in limit_markers) or (
            code in {4, 9, 17, 32, 613} and "limit" in normalized
        ):
            raise UploadLimitError("Instagram", detail)
        raise UploadError(f"{operation} failed: {detail}")
