class WorkflowError(Exception):
    """A user-facing workflow failure."""


class ConfigurationError(WorkflowError):
    """Invalid or incomplete runtime configuration."""


class DownloadError(WorkflowError):
    """A source video could not be downloaded."""


class MediaError(WorkflowError):
    """FFmpeg/ffprobe failed to process media."""


class AIError(WorkflowError):
    """AI transcription or planning failed."""


class UploadError(WorkflowError):
    """A platform upload failed."""


class DirectMessageError(UploadError):
    """Sending a generated video to the configured direct-message chat failed."""


class UploadLimitError(UploadError):
    """A platform's daily/rate publishing allowance was exhausted."""

    def __init__(self, platform: str, detail: str) -> None:
        self.platform = platform
        self.detail = detail
        super().__init__(f"{platform} upload limit reached: {detail}")
