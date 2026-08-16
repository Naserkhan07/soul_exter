# Groq YouTube Shorts + Instagram Reels Automation

A private Telegram bot and file-driven workflow that accepts authorized YouTube links, downloads each source video, asks **Groq** to select a compelling 20–30 second excerpt, renders a vertical 9:16 video, generates platform-specific metadata, and publishes it as a public YouTube Short and Instagram Reel.

> **Only use videos you own or have explicit permission/license to download, edit, and republish.** A public video is not automatically free to reuse. Attribution does not replace permission, and downloading may be restricted by YouTube's Terms of Service. The application will not run until `RIGHTS_ACKNOWLEDGED=true`.

## Features

- Groq `whisper-large-v3-turbo` timestamped transcription
- Groq Llama highlight selection, YouTube title/description, and Instagram caption
- 20–30 second 1080×1920 H.264/AAC output
- Telegram `/short` command accepting several links
- Automated `links.txt` queue
- Atomic removal of a URL immediately after its video downloads successfully
- Permanent downloaded-link audit log at `work/downloaded-links.log`
- Public YouTube Shorts through the official YouTube Data API
- Instagram Reels through Meta's official resumable Graph API upload
- Reels shared to the Instagram feed with `share_to_feed=true`
- SQLite job history and partial-upload tracking
- Docker and command-line operation

## Important: do not store account passwords

This project intentionally does **not** accept or save a YouTube, Google, Facebook, or Instagram password.

- YouTube publishing uses the official Google OAuth flow and `youtube_token.json`.
- Instagram publishing uses a Meta access token for a Professional account.
- `channels.toml` contains only non-secret numeric account/channel IDs.
- `.env`, OAuth files, access tokens, and the `credentials/` directory are gitignored.

Password-based browser automation is insecure, can trigger account challenges, and can violate platform rules.

## Workflow

1. Add one YouTube URL per line to `links.txt`, paste links into Telegram, or use `shorts-cli`.
2. `yt-dlp` downloads one source video per URL; playlists are disabled.
3. For file-queue jobs, the exact URL is atomically removed from `links.txt` as soon as the download succeeds and is written to `work/downloaded-links.log`.
4. FFmpeg extracts speech audio.
5. Groq transcribes the audio and selects a contiguous 20–30 second highlight.
6. Groq creates a YouTube title/description and a separate Instagram caption.
7. FFmpeg renders a center-cropped 1080×1920 MP4.
8. The workflow uploads the Short to YouTube with `privacyStatus=public`.
9. It uploads and publishes the same file as an Instagram Reel and shares it to the feed.

A URL is removed **after download**, exactly as requested. If later AI, rendering, or publishing fails, it remains in `work/downloaded-links.log` with its job ID but is not automatically put back in `links.txt`. This prevents unintended duplicate downloads; copy it back manually when you want to retry.

## Requirements

- Python 3.11+
- FFmpeg and ffprobe
- Groq API key
- Telegram bot token from [@BotFather](https://t.me/BotFather), for bot mode
- Google Cloud OAuth desktop client with YouTube Data API v3 enabled
- Instagram Business or Creator account and Meta Graph API access token

Instagram's official publishing API does not support ordinary personal accounts. Depending on the Meta login configuration, the Professional account may need to be connected to a Facebook Page and the app needs content-publishing permissions.

## Install

```bash
git clone <repository-url>
cd soul_exter
python -m venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\activate
pip install -e '.[dev]'
cp .env.example .env
```

Install FFmpeg if needed:

```bash
# Ubuntu/Debian
sudo apt-get install ffmpeg

# macOS
brew install ffmpeg
```

## Configure Groq

Edit `.env`:

```dotenv
GROQ_API_KEY=gsk_your_key
GROQ_MODEL=llama-3.3-70b-versatile
GROQ_TRANSCRIPTION_MODEL=whisper-large-v3-turbo
RIGHTS_ACKNOWLEDGED=true
```

No OpenAI key or OpenAI service is used.

## Configure account IDs

Edit `channels.toml`:

```toml
[youtube]
channel_id = "UC_YOUR_CHANNEL_ID"

[instagram]
user_id = "YOUR_NUMERIC_INSTAGRAM_PROFESSIONAL_ACCOUNT_ID"
```

Do not put passwords or access tokens in this file.

## Authorize public YouTube uploads

1. Create/select a project in Google Cloud Console.
2. Enable **YouTube Data API v3**.
3. Configure the OAuth consent screen and add your Google account as a test user if needed.
4. Create an OAuth client with application type **Desktop app**.
5. Download it to `client_secret.json`.
6. Run:

```bash
shorts-auth
```

This opens Google's consent page and writes `youtube_token.json`. The app requests upload access plus read-only channel identity access so it can verify that OAuth matches the `channel_id` in `channels.toml` before uploading. A channel password is neither needed nor accepted. If you created a token with an older version of this project, delete it and run `shorts-auth` again.

Configure `.env`:

```dotenv
UPLOAD_YOUTUBE=true
YOUTUBE_PRIVACY_STATUS=public
YOUTUBE_CLIENT_SECRETS_FILE=client_secret.json
YOUTUBE_TOKEN_FILE=youtube_token.json
```

**Google limitation:** YouTube can lock API uploads from an unverified API project to private even when the request asks for `public`. A Google API compliance audit may be required before the project can publish publicly. The workflow requests public visibility but cannot bypass this Google restriction.

## Configure Instagram Reels publishing

Use Meta for Developers to configure the Instagram Graph API/Facebook Login for Business flow for your Professional account. Obtain a valid access token with the required basic/account and content-publishing permissions, then set:

```dotenv
UPLOAD_INSTAGRAM=true
INSTAGRAM_ACCESS_TOKEN=your_long_lived_meta_access_token
INSTAGRAM_GRAPH_API_VERSION=v25.0
```

The token is sent only to Meta Graph API endpoints. Keep it in `.env`; never commit it. Meta tokens expire or can be revoked, so renew them according to your app's token lifecycle.

The uploader uses Meta's local-file resumable flow:

1. Creates a `REELS` container with `upload_type=resumable`
2. Uploads the MP4 to the returned `rupload.facebook.com` URI
3. Waits for `status_code=FINISHED`
4. Calls `media_publish`
5. Reads the public permalink

The Reel is also shared to the account feed. Actual visibility is still governed by the Instagram account and Meta's policies.

## Automated `links.txt` queue

Add one URL per line:

```text
https://www.youtube.com/watch?v=VIDEO_ONE
https://youtu.be/VIDEO_TWO
https://youtube.com/shorts/VIDEO_THREE
```

Start the watcher:

```bash
shorts-queue
```

It checks the file every 30 seconds by default. Process only the current contents and exit with:

```bash
shorts-queue --once
```

Queue-related configuration:

```dotenv
LINKS_FILE=links.txt
DOWNLOADED_LINKS_LOG=work/downloaded-links.log
LINKS_POLL_SECONDS=30
```

Comments beginning with `#` and blank lines are preserved. Duplicate URL lines are all removed after the first successful download.

## Telegram bot

Configure:

```dotenv
TELEGRAM_BOT_TOKEN=123456:telegram-token
ALLOWED_TELEGRAM_USER_IDS=123456789
```

`ALLOWED_TELEGRAM_USER_IDS` is mandatory and prevents strangers from publishing to your accounts.

Run:

```bash
shorts-bot
```

Commands:

- `/short URL [URL ...]` — queue up to `MAX_URLS_PER_COMMAND` links
- `/status` — show recent jobs and both platform links
- `/status JOB_ID` — inspect one job
- `/help` — show instructions

You can also paste one or more YouTube links without a command.

## One-off command-line runs

Use the platforms configured in `.env`:

```bash
shorts-cli 'https://youtu.be/VIDEO_ID'
```

Override platforms:

```bash
shorts-cli --platform both 'https://youtu.be/VIDEO_ID'
shorts-cli --platform youtube 'https://youtu.be/VIDEO_ID'
shorts-cli --platform instagram 'https://youtu.be/VIDEO_ID'
shorts-cli --platform none 'https://youtu.be/VIDEO_ID'
```

## Docker

Prepare credentials:

```bash
mkdir -p credentials
cp channels.toml credentials/channels.toml
cp client_secret.json youtube_token.json credentials/
```

Then start both Telegram intake and the watched link queue:

```bash
docker compose up --build -d
docker compose logs -f
```

`links.txt` is mounted directly, while `work/` and `credentials/` persist job state and refreshed OAuth credentials.

Run only one interface if desired:

```bash
docker compose up --build -d link-queue
docker compose up --build -d shorts-bot
```

## Configuration reference

| Variable | Default | Purpose |
|---|---:|---|
| `GROQ_API_KEY` | empty | Required Groq API key |
| `GROQ_MODEL` | `llama-3.3-70b-versatile` | Highlight and metadata model |
| `GROQ_TRANSCRIPTION_MODEL` | `whisper-large-v3-turbo` | Timestamped transcription model |
| `CHANNEL_CONFIG_FILE` | `channels.toml` | Non-secret YouTube/Instagram IDs |
| `UPLOAD_YOUTUBE` | `false` | Enable YouTube publishing |
| `YOUTUBE_PRIVACY_STATUS` | `public` | Requested YouTube visibility |
| `YOUTUBE_TOKEN_FILE` | `youtube_token.json` | Generated OAuth token |
| `UPLOAD_INSTAGRAM` | `false` | Enable Instagram publishing |
| `INSTAGRAM_ACCESS_TOKEN` | empty | Secret Meta access token |
| `INSTAGRAM_GRAPH_API_VERSION` | `v25.0` | Meta Graph API version |
| `LINKS_FILE` | `links.txt` | Watched line-based URL queue |
| `DOWNLOADED_LINKS_LOG` | `work/downloaded-links.log` | Download acknowledgement log |
| `LINKS_POLL_SECONDS` | `30` | Queue polling interval, 5–3600 |
| `TELEGRAM_BOT_TOKEN` | empty | Telegram bot token |
| `ALLOWED_TELEGRAM_USER_IDS` | empty | Comma-separated private allowlist |
| `CLIP_DURATION_SECONDS` | `25` | Preferred duration, 20–30 |
| `MAX_URLS_PER_COMMAND` | `5` | Telegram batch size, 1–10 |
| `WORK_DIR` | `work` | Runtime media directory |
| `DATABASE_PATH` | `work/jobs.db` | SQLite job database |
| `KEEP_WORK_FILES` | `true` | Keep local MP4s after publishing |
| `RIGHTS_ACKNOWLEDGED` | `false` | Must be explicitly enabled |

`AUTO_UPLOAD` remains a backwards-compatible alias for `UPLOAD_YOUTUBE`, but new setups should use the explicit platform variables.

## Development

```bash
ruff check .
pytest
```

Main components:

- `downloader.py` — strict YouTube URL intake and `yt-dlp`
- `ai.py` — Groq transcription, highlight selection, and captions
- `media.py` — FFmpeg rendering
- `youtube.py` — YouTube OAuth resumable uploads
- `instagram.py` — Instagram Graph API resumable Reel publishing
- `file_queue.py` — atomic `links.txt` queue acknowledgement
- `pipeline.py` — state machine and multi-platform publishing
- `bot.py` / `cli.py` — Telegram and command-line interfaces

### Operational notes

- Landscape source video is center-cropped to fill 9:16; review framing before scaling up automation.
- AI can make poor editorial choices. Test with accounts/content where mistakes are easy to remove.
- The downloader does not bypass private videos, DRM, region restrictions, or account controls.
- YouTube and Instagram can reject content for policy, copyright, token, quota, verification, or media-processing reasons.
- Protect `.env`, `client_secret.json`, `youtube_token.json`, and the `credentials/` directory.
