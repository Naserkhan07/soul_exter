from __future__ import annotations

from google_auth_oauthlib.flow import InstalledAppFlow

from .config import Settings
from .errors import ConfigurationError
from .youtube import YOUTUBE_SCOPES


def main() -> None:
    settings = Settings.from_env()
    secret_file = settings.youtube_client_secrets_file
    if not secret_file.exists():
        raise ConfigurationError(
            f"OAuth client secrets file not found at {secret_file}. "
            "Download it from Google Cloud Console first."
        )
    settings.youtube_token_file.parent.mkdir(parents=True, exist_ok=True)
    flow = InstalledAppFlow.from_client_secrets_file(str(secret_file), scopes=YOUTUBE_SCOPES)
    credentials = flow.run_local_server(port=0, open_browser=True)
    settings.youtube_token_file.write_text(credentials.to_json(), encoding="utf-8")
    print(f"YouTube authorization saved to {settings.youtube_token_file}")


if __name__ == "__main__":
    main()
