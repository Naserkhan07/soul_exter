# AI YouTube Shorts Bot

A private Telegram bot and command-line workflow that accepts one or more YouTube links, downloads each authorized source video, uses AI to select a compelling 20–30 second excerpt, renders it as a 9:16 MP4, generates a title and description, and can upload it to YouTube automatically.

> **Use only videos you own or have explicit permission/license to download, edit, and republish.** A public video is not automatically free to reuse. Attribution does not replace permission, and downloading may also be restricted by YouTube's Terms of Service. This project requires `RIGHTS_ACKNOWLEDGED=true` before it will process anything.

## How it works

1. `/short <youtube-url> [more URLs]` queues one job per URL.
2. `yt-dlp` downloads one video per link (playlists are disabled).
3. FFmpeg creates a small speech audio track.
4. OpenAI transcribes it and chooses a contiguous highlight between 20 and 30 seconds.
5. FFmpeg center-crops/scales the excerpt to 1080×1920, H.264/AAC.
6. AI-generated metadata is combined with reliable source attribution and `#Shorts`.
7. The result is either sent back through Telegram or uploaded to the authorized YouTube channel.

Uploads default to **private** and automatic upload defaults to **off**, so the first run is safe to review.

## Requirements

- Python 3.11+
- FFmpeg and ffprobe
- An OpenAI API key
- A private Telegram bot token from [@BotFather](https://t.me/BotFather) (for bot mode)
- A Google Cloud OAuth desktop client with **YouTube Data API v3** enabled (for uploads)

## Setup

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

Edit `.env`:

```dotenv
TELEGRAM_BOT_TOKEN=123456:telegram-token
ALLOWED_TELEGRAM_USER_IDS=123456789
OPENAI_API_KEY=sk-...
RIGHTS_ACKNOWLEDGED=true

# Keep these safe defaults for the first test
AUTO_UPLOAD=false
YOUTUBE_PRIVACY_STATUS=private
```

`ALLOWED_TELEGRAM_USER_IDS` is mandatory in bot mode. It prevents strangers from using your OAuth-authorized channel. You can get your numeric user ID from a Telegram ID bot such as `@userinfobot` before starting this service.

## Authorize YouTube uploads

1. In Google Cloud Console, create/select a project.
2. Enable **YouTube Data API v3**.
3. Configure the OAuth consent screen. While the app is in testing, add your Google account as a test user.
4. Create an OAuth client with application type **Desktop app**.
5. Download its JSON file to `client_secret.json` (the filename is gitignored).
6. Run authorization on a machine with a browser:

```bash
shorts-auth
```

This creates `youtube_token.json`, which is also gitignored. Never commit or send either credentials file. If the bot runs on a server, authorize on your desktop and securely copy only the token and client secret to the server.

Then set:

```dotenv
AUTO_UPLOAD=true
YOUTUBE_PRIVACY_STATUS=private  # change to unlisted/public only when ready
```

The YouTube API charges quota per upload, even for failed or private uploads. Google may also require the OAuth app/project to pass an audit before uploads from an unverified API project can be made public.

## Run the Telegram bot

```bash
shorts-bot
# or: python -m shorts_bot.bot
```

Telegram commands:

- `/short URL [URL ...]` — queue up to `MAX_URLS_PER_COMMAND` videos
- `/status` — show the ten most recent jobs
- `/status JOB_ID` — inspect one job
- `/help` — instructions

You can also paste one or more YouTube links without `/short`. Jobs are processed sequentially to avoid exhausting CPU/RAM. The SQLite database at `work/jobs.db` keeps job history across restarts.

## Run without Telegram

```bash
shorts-cli --no-upload 'https://www.youtube.com/watch?v=VIDEO_ID'
shorts-cli --upload 'https://youtu.be/VIDEO_ID' 'https://youtube.com/shorts/VIDEO_ID'
```

Rendered videos are stored under `work/jobs/<job-id>/short.mp4`.

## Docker

Authorize YouTube and create `.env` before starting the container. Docker Compose uses a gitignored
`credentials/` directory; it can stay empty when uploads are disabled.

```bash
mkdir -p credentials
# Required only when AUTO_UPLOAD=true:
cp client_secret.json youtube_token.json credentials/

docker compose up --build -d
docker compose logs -f
```

The `work/` and `credentials/` directories are mounted so jobs and the refreshed OAuth token survive
container replacement.

## Configuration

| Variable | Default | Purpose |
|---|---:|---|
| `TELEGRAM_BOT_TOKEN` | empty | Telegram token; required in bot mode |
| `ALLOWED_TELEGRAM_USER_IDS` | empty | Comma-separated allowlist; required in bot mode |
| `OPENAI_API_KEY` | empty | Required for transcription and highlight planning |
| `OPENAI_MODEL` | `gpt-4o-mini` | Metadata/highlight model |
| `OPENAI_TRANSCRIPTION_MODEL` | `whisper-1` | Timestamped transcription model |
| `AUTO_UPLOAD` | `false` | Upload finished Shorts to YouTube |
| `YOUTUBE_PRIVACY_STATUS` | `private` | `private`, `unlisted`, or `public` |
| `YOUTUBE_CLIENT_SECRETS_FILE` | `client_secret.json` | Google OAuth desktop client file |
| `YOUTUBE_TOKEN_FILE` | `youtube_token.json` | Generated OAuth token |
| `CLIP_DURATION_SECONDS` | `25` | Preferred length; must be 20–30 |
| `MAX_URLS_PER_COMMAND` | `5` | Batch size; 1–10 |
| `WORK_DIR` | `work` | Download/render directory |
| `DATABASE_PATH` | `work/jobs.db` | SQLite job database |
| `KEEP_WORK_FILES` | `true` | Keep local files after successful upload |
| `RIGHTS_ACKNOWLEDGED` | `false` | Must be explicitly set to `true` |

## Development

```bash
ruff check .
pytest
```

The main components are deliberately separated for testing:

- `downloader.py` — strict YouTube URL intake and `yt-dlp`
- `ai.py` — timestamped transcription, highlight choice, and metadata normalization
- `media.py` — FFmpeg extraction/rendering
- `youtube.py` — resumable YouTube upload
- `pipeline.py` — job state machine and sequential queue
- `bot.py` / `cli.py` — user interfaces

### Operational notes

- Landscape video is center-cropped to fill 9:16. Review output before public publishing; important action near the edges may be lost.
- The AI can make poor editorial choices. `private` uploads and `AUTO_UPLOAD=false` are recommended until the workflow is validated.
- The bot does not bypass private videos, DRM, region restrictions, or account controls.
- Keep the bot allowlist narrow and protect `.env`, `client_secret.json`, and `youtube_token.json`.
