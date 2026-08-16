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
    """YouTube upload failed."""
