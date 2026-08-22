from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

import httpx

from .errors import UploadError, UploadLimitError
from .models import ShortPlan

logger = logging.getLogger(__name__)


class FacebookReelUploader:
    """Publish local MP4 files as public Facebook Page Reels."""

    def __init__(
        self,
        page_id: str,
        access_token: str,
        api_version: str = "v26.0",
        poll_interval_seconds: int = 5,
        processing_timeout_seconds: int = 900,
        retry_attempts: int = 4,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.page_id = page_id
        self.access_token = access_token
        self.api_version = api_version
        self.poll_interval_seconds = poll_interval_seconds
        self.processing_timeout_seconds = processing_timeout_seconds
        self.retry_attempts = max(1, retry_attempts)
        self.transport = transport
        self.graph_base = f"https://graph.facebook.com/{api_version}"

    async def check_connection(self) -> str:
        timeout = httpx.Timeout(60, read=120)
        async with httpx.AsyncClient(timeout=timeout, transport=self.transport) as client:
            page = await self._get_json(
                client,
                f"{self.graph_base}/{self.page_id}",
                params={
                    "fields": "id,name,tasks",
                    "access_token": self.access_token,
                },
            )
        returned_id = str(page.get("id") or "")
        if returned_id != self.page_id:
            raise UploadError(
                f"Facebook token returned Page {returned_id or 'unknown'}, expected {self.page_id}."
            )
        tasks = {str(task) for task in page.get("tasks", [])}
        if tasks and "CREATE_CONTENT" not in tasks:
            raise UploadError("Facebook token does not have CREATE_CONTENT access on the Page.")
        return str(page.get("name") or returned_id)

    async def upload(self, video_path: Path, plan: ShortPlan) -> tuple[str, str]:
        if not video_path.exists():
            raise UploadError(f"Rendered Facebook Reel does not exist: {video_path}")

        timeout = httpx.Timeout(120, read=900)
        async with httpx.AsyncClient(timeout=timeout, transport=self.transport) as client:
            session = await self._post_json(
                client,
                f"{self.graph_base}/{self.page_id}/video_reels",
                data={
                    "upload_phase": "start",
                    "access_token": self.access_token,
                },
                operation="Facebook Reel upload-session creation",
            )
            video_id = str(session.get("video_id") or "")
            upload_url = str(session.get("upload_url") or "")
            if not video_id or not upload_url:
                raise UploadError("Facebook returned no Reel video ID or upload URL.")

            await self._upload_binary(client, upload_url, video_path)
            description = f"{plan.title}\n\n{plan.description}".strip()
            await self._post_json(
                client,
                f"{self.graph_base}/{self.page_id}/video_reels",
                data={
                    "upload_phase": "finish",
                    "video_id": video_id,
                    "video_state": "PUBLISHED",
                    "description": description,
                    "access_token": self.access_token,
                },
                operation="Facebook Reel publishing",
            )
            permalink = await self._wait_until_published(client, video_id)
        return video_id, permalink or f"https://www.facebook.com/reel/{video_id}"

    async def _upload_binary(
        self,
        client: httpx.AsyncClient,
        upload_url: str,
        video_path: Path,
    ) -> None:
        file_size = video_path.stat().st_size
        for attempt in range(1, self.retry_attempts + 1):
            try:
                with video_path.open("rb") as video_file:
                    response = await client.post(
                        upload_url,
                        headers={
                            "Authorization": f"OAuth {self.access_token}",
                            "Content-Type": "application/octet-stream",
                            "offset": "0",
                            "file_size": str(file_size),
                        },
                        content=video_file.read(),
                    )
                if response.is_success:
                    payload = self._json(response, "Facebook Reel binary upload")
                    if payload.get("success") is not False:
                        return
                if response.status_code < 500 or attempt == self.retry_attempts:
                    self._raise_for_meta_error(response, "Facebook Reel binary upload")
            except UploadLimitError:
                raise
            except UploadError:
                raise
            except httpx.HTTPError as exc:
                if attempt == self.retry_attempts:
                    raise UploadError(
                        "Facebook Reel binary upload failed after automatic retries."
                    ) from exc

            delay = min(30, 2 ** (attempt - 1))
            logger.warning(
                "Facebook Reel upload returned a temporary error; retrying in %s seconds (%s/%s)",
                delay,
                attempt + 1,
                self.retry_attempts,
            )
            await asyncio.sleep(delay)
        raise UploadError("Facebook Reel binary upload ended without a result.")

    async def _wait_until_published(self, client: httpx.AsyncClient, video_id: str) -> str:
        attempts = max(1, self.processing_timeout_seconds // self.poll_interval_seconds)
        for _ in range(attempts):
            result = await self._get_json(
                client,
                f"{self.graph_base}/{video_id}",
                params={
                    "fields": "status,permalink_url",
                    "access_token": self.access_token,
                },
            )
            status = result.get("status", {})
            if not isinstance(status, dict):
                status = {}
            video_status = str(status.get("video_status") or "").casefold()
            publishing = status.get("publishing_phase", {})
            publishing_status = (
                str(publishing.get("status") or "").casefold()
                if isinstance(publishing, dict)
                else ""
            )
            if video_status in {"ready", "published"} or publishing_status == "complete":
                return str(result.get("permalink_url") or "")
            processing = status.get("processing_phase", {})
            processing_status = (
                str(processing.get("status") or "").casefold()
                if isinstance(processing, dict)
                else ""
            )
            if video_status in {"error", "failed"} or processing_status == "error":
                detail = processing.get("error") if isinstance(processing, dict) else None
                raise UploadError(f"Facebook could not process the Reel: {detail or status}")
            await asyncio.sleep(self.poll_interval_seconds)
        raise UploadError("Facebook Reel processing timed out before publication.")

    async def _post_json(
        self,
        client: httpx.AsyncClient,
        url: str,
        data: dict[str, str],
        operation: str,
    ) -> dict[str, Any]:
        try:
            response = await client.post(url, data=data)
            self._raise_for_meta_error(response, operation)
            return self._json(response, operation)
        except (UploadError, UploadLimitError):
            raise
        except httpx.HTTPError as exc:
            raise UploadError(f"{operation} network request failed.") from exc

    async def _get_json(
        self,
        client: httpx.AsyncClient,
        url: str,
        params: dict[str, str],
    ) -> dict[str, Any]:
        try:
            response = await client.get(url, params=params)
            self._raise_for_meta_error(response, "Facebook Graph API")
            return self._json(response, "Facebook Graph API")
        except (UploadError, UploadLimitError):
            raise
        except httpx.HTTPError as exc:
            raise UploadError("Facebook Graph API network request failed.") from exc

    @staticmethod
    def _json(response: httpx.Response, operation: str) -> dict[str, Any]:
        try:
            payload = response.json()
        except ValueError as exc:
            raise UploadError(f"{operation} returned invalid JSON.") from exc
        if not isinstance(payload, dict):
            raise UploadError(f"{operation} returned invalid data.")
        return payload

    @classmethod
    def _raise_for_meta_error(cls, response: httpx.Response, operation: str) -> None:
        if response.is_success:
            return
        detail = f"HTTP {response.status_code}"
        code = 0
        try:
            payload = response.json()
            error = payload.get("error", {}) if isinstance(payload, dict) else {}
            if isinstance(error, dict):
                detail = str(error.get("error_user_msg") or error.get("message") or detail)
                code = int(error.get("code") or 0)
        except (ValueError, TypeError, AttributeError):
            body = response.text.strip()
            if body:
                detail = f"HTTP {response.status_code}: {body[:500]}"

        normalized = f"{detail} {response.text}".casefold()
        limit_markers = (
            "rate limit",
            "too many",
            "30 api-published",
            "publishing limit",
            "application request limit",
            "quota",
        )
        if (
            response.status_code == 429
            or any(marker in normalized for marker in limit_markers)
            or (code in {4, 17, 32, 613} and "limit" in normalized)
        ):
            raise UploadLimitError("Facebook", detail)
        raise UploadError(f"{operation} failed: {detail}")
