from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any, Protocol

import cloudinary
import cloudinary.api
import cloudinary.uploader
import httpx

from .errors import WorkflowError

logger = logging.getLogger(__name__)


class EnhancementError(WorkflowError):
    """A remote video enhancement operation failed."""


class TemporaryVideoHost(Protocol):
    async def check_connection(self) -> None: ...

    async def upload(self, video_path: Path, public_id: str) -> tuple[str, str]: ...

    async def delete(self, public_id: str) -> None: ...


class CloudinaryTemporaryVideoHost:
    def __init__(self, cloud_name: str, api_key: str, api_secret: str) -> None:
        cloudinary.config(
            cloud_name=cloud_name,
            api_key=api_key,
            api_secret=api_secret,
            secure=True,
        )

    async def check_connection(self) -> None:
        try:
            await asyncio.to_thread(cloudinary.api.ping)
        except Exception as exc:
            raise EnhancementError(f"Cloudinary credential check failed: {exc}") from exc

    async def upload(self, video_path: Path, public_id: str) -> tuple[str, str]:
        try:
            result = await asyncio.to_thread(
                cloudinary.uploader.upload_large,
                str(video_path),
                resource_type="video",
                public_id=public_id,
                overwrite=True,
            )
            url = str(result.get("secure_url") or "")
            stored_id = str(result.get("public_id") or public_id)
            if not url:
                raise EnhancementError("Cloudinary returned no secure video URL.")
            return url, stored_id
        except EnhancementError:
            raise
        except Exception as exc:
            raise EnhancementError(f"Temporary Cloudinary upload failed: {exc}") from exc

    async def delete(self, public_id: str) -> None:
        try:
            await asyncio.to_thread(
                cloudinary.uploader.destroy,
                public_id,
                resource_type="video",
                invalidate=True,
            )
        except Exception:
            logger.warning("Could not delete temporary Cloudinary video %s", public_id)


class APIMarketVideoEnhancer:
    def __init__(
        self,
        api_key: str,
        temporary_host: TemporaryVideoHost,
        base_url: str,
        version: str,
        model: str = "RealESRGAN_x4plus",
        resolution: str = "FHD",
        timeout_seconds: int = 1_200,
        poll_interval_seconds: int = 5,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.api_key = api_key
        self.temporary_host = temporary_host
        self.base_url = base_url.rstrip("/")
        self.version = version
        self.model = model
        self.resolution = resolution
        self.timeout_seconds = timeout_seconds
        self.poll_interval_seconds = poll_interval_seconds
        self.transport = transport

    async def check_connection(self) -> None:
        await self.temporary_host.check_connection()

    async def enhance(self, video_path: Path, output_path: Path, public_id: str) -> Path:
        if not video_path.exists():
            raise EnhancementError(f"Clip to enhance does not exist: {video_path}")

        hosted_id = public_id
        hosted_url = ""
        try:
            hosted_url, hosted_id = await self.temporary_host.upload(video_path, public_id)
            timeout = httpx.Timeout(120, read=300)
            async with httpx.AsyncClient(
                timeout=timeout,
                follow_redirects=True,
                transport=self.transport,
            ) as client:
                prediction_id = await self._create_prediction(client, hosted_url)
                result_url = await self._wait_for_result(client, prediction_id)
                await self._download_result(client, result_url, output_path)
            return output_path
        finally:
            if hosted_url:
                await self.temporary_host.delete(hosted_id)

    @property
    def _headers(self) -> dict[str, str]:
        # API.market's store page and playground have used both names; sending both keeps
        # compatibility while transmitting the key only to the documented API.market host.
        return {
            "Content-Type": "application/json",
            "x-magicapi-key": self.api_key,
            "x-api-market-key": self.api_key,
        }

    async def _create_prediction(self, client: httpx.AsyncClient, video_url: str) -> str:
        response = await client.post(
            f"{self.base_url}/predictions",
            headers=self._headers,
            json={
                "version": self.version,
                "input": {
                    "model": self.model,
                    "resolution": self.resolution,
                    "video_path": video_url,
                },
            },
        )
        payload = self._response_json(response, "create prediction")
        prediction_id = _find_string(payload, "id")
        if not prediction_id:
            raise EnhancementError("API.market returned no prediction ID.")
        return prediction_id

    async def _wait_for_result(self, client: httpx.AsyncClient, prediction_id: str) -> str:
        elapsed = 0
        while elapsed <= self.timeout_seconds:
            response = await client.get(
                f"{self.base_url}/predictions/{prediction_id}",
                headers=self._headers,
            )
            payload = self._response_json(response, "check prediction")
            status = str(_find_value(payload, "status") or "").lower()
            if status == "succeeded":
                output = _find_value(payload, "output")
                result_url = _first_url(output)
                if not result_url:
                    raise EnhancementError("API.market succeeded but returned no output URL.")
                return result_url
            if status in {"failed", "canceled", "cancelled"}:
                detail = _find_value(payload, "error") or "Unknown enhancement error"
                raise EnhancementError(f"API.market enhancement failed: {detail}")
            await asyncio.sleep(self.poll_interval_seconds)
            elapsed += self.poll_interval_seconds
        raise EnhancementError(
            f"API.market enhancement timed out after {self.timeout_seconds} seconds."
        )

    async def _download_result(
        self,
        client: httpx.AsyncClient,
        result_url: str,
        output_path: Path,
    ) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = output_path.with_suffix(output_path.suffix + ".part")
        try:
            async with client.stream("GET", result_url) as response:
                response.raise_for_status()
                with temporary.open("wb") as output_file:
                    async for chunk in response.aiter_bytes():
                        output_file.write(chunk)
            if not temporary.exists() or temporary.stat().st_size == 0:
                raise EnhancementError("API.market returned an empty enhanced video.")
            temporary.replace(output_path)
        except EnhancementError:
            raise
        except httpx.HTTPError as exc:
            raise EnhancementError(f"Could not download enhanced video: {exc}") from exc
        finally:
            temporary.unlink(missing_ok=True)

    @staticmethod
    def _response_json(response: httpx.Response, operation: str) -> Any:
        if not response.is_success:
            detail = f"HTTP {response.status_code}"
            try:
                payload = response.json()
                detail = str(
                    _find_value(payload, "message") or _find_value(payload, "error") or detail
                )
            except ValueError:
                pass
            raise EnhancementError(f"API.market {operation} failed: {detail}")
        try:
            return response.json()
        except ValueError as exc:
            raise EnhancementError(f"API.market {operation} returned invalid JSON.") from exc


def _find_value(value: Any, key: str) -> Any:
    if isinstance(value, dict):
        if key in value:
            return value[key]
        for nested in value.values():
            result = _find_value(nested, key)
            if result is not None:
                return result
    elif isinstance(value, list):
        for nested in value:
            result = _find_value(nested, key)
            if result is not None:
                return result
    return None


def _find_string(value: Any, key: str) -> str:
    found = _find_value(value, key)
    return str(found) if found is not None else ""


def _first_url(value: Any) -> str:
    if isinstance(value, str) and value.startswith(("https://", "http://")):
        return value
    if isinstance(value, dict):
        for nested in value.values():
            result = _first_url(nested)
            if result:
                return result
    if isinstance(value, list):
        for nested in value:
            result = _first_url(nested)
            if result:
                return result
    return ""
