# Local Groq Shorts + Instagram Reels Automation

This project runs entirely on your laptop from VS Code. There is no Telegram bot, web server, cloud worker, or Docker requirement.

Add authorized YouTube links to `links.txt`. The local program downloads each video, removes its link from the file after a successful download, uses Groq to select a 20–30 second highlight and generate metadata, renders a vertical Short, and publishes it to YouTube and Instagram.

> **Only process videos you own or have explicit permission/license to download, edit, and republish.** A publicly viewable video is not automatically licensed for reuse. The program requires `RIGHTS_ACKNOWLEDGED=true`.

## What the local workflow does

1. Watches the local `links.txt` file.
2. Downloads one authorized YouTube video at a time with `yt-dlp`.
3. Removes every matching URL line immediately after the video downloads successfully.
4. Records the URL and job ID in `work/downloaded-links.log`.
5. Extracts speech audio locally with FFmpeg.
6. Uses Groq `whisper-large-v3-turbo` for timestamped transcription.
7. Uses Groq Llama to select one contiguous 20–30 second highlight.
8. Generates a YouTube title/description and a separate Instagram caption.
9. Renders a 1080×1920 H.264/AAC MP4 locally.
10. Uploads it as a public YouTube Short and an Instagram Reel shared to the feed.

A downloaded URL is removed before AI/render/upload starts. If a later stage fails, the URL remains in `work/downloaded-links.log`; copy it back into `links.txt` when you want to retry.

## Local files

- `main.py` — easiest way to start the watcher from VS Code
- `links.txt` — paste one YouTube URL per line
- `channels.toml` — non-secret YouTube and Instagram account IDs
- `.env` — local API keys and tokens; never committed
- `client_secret.json` — Google OAuth desktop client; never committed
- `youtube_token.json` — generated Google OAuth token; never committed
- `work/jobs.db` — local job history
- `work/jobs/<job-id>/short.mp4` — rendered Shorts/Reels
- `work/downloaded-links.log` — downloaded URL audit history

## Do not save account passwords

The program intentionally does not accept YouTube, Google, Facebook, or Instagram passwords.

- YouTube upload uses Google's official OAuth browser authorization.
- Instagram upload uses a Meta access token for a Professional account.
- `channels.toml` contains only non-secret IDs.
- Secret values stay in the gitignored `.env` and OAuth files on your laptop.

## 1. Install local requirements

Install:

- Python 3.11 or newer
- VS Code
- VS Code Python extension
- FFmpeg and ffprobe

### Windows FFmpeg

Using Winget:

```powershell
winget install Gyan.FFmpeg
```

Restart VS Code after installation and verify:

```powershell
ffmpeg -version
ffprobe -version
```

### macOS

```bash
brew install ffmpeg
```

### Ubuntu/Debian

```bash
sudo apt-get update
sudo apt-get install ffmpeg
```

## 2. Open and install in VS Code

Open the repository folder in VS Code.

### Windows PowerShell

```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
Copy-Item .env.example .env
```

If PowerShell blocks activation, either select `.venv` through **Python: Select Interpreter**, or temporarily allow the current process:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.venv\Scripts\Activate.ps1
```

### macOS/Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
cp .env.example .env
```

In VS Code, select the `.venv` interpreter using **Python: Select Interpreter**.

A VS Code task named **Install project dependencies** is also included.

## 3. Configure Groq locally

Edit `.env`:

```dotenv
GROQ_API_KEY=gsk_your_key
GROQ_MODEL=llama-3.3-70b-versatile
GROQ_TRANSCRIPTION_MODEL=whisper-large-v3-turbo
RIGHTS_ACKNOWLEDGED=true
```

No OpenAI API key or OpenAI service is used.

## 4. Configure local account IDs

Edit `channels.toml`:

```toml
[youtube]
channel_id = "UC_YOUR_CHANNEL_ID"

[instagram]
user_id = "YOUR_NUMERIC_INSTAGRAM_PROFESSIONAL_ACCOUNT_ID"
```

Do not put passwords or access tokens in this file.

## 5. Authorize YouTube from your laptop

1. Open Google Cloud Console.
2. Create/select a project and enable **YouTube Data API v3**.
3. Configure the OAuth consent screen.
4. Create an OAuth client with application type **Desktop app**.
5. Download the file and save it in this project as `client_secret.json`.
6. Run in the VS Code terminal:

```bash
python -m shorts_bot.youtube_auth
```

Alternatively, select **Authorize YouTube** in VS Code's Run and Debug menu.

Your browser opens Google's official consent screen. The result is saved locally as `youtube_token.json`. The program verifies that the authorized channel matches `channels.toml` before uploading.

Configure `.env`:

```dotenv
UPLOAD_YOUTUBE=true
YOUTUBE_PRIVACY_STATUS=public
YOUTUBE_CLIENT_SECRETS_FILE=client_secret.json
YOUTUBE_TOKEN_FILE=youtube_token.json
```

YouTube may lock uploads from an unaudited Google API project to private even when `public` is requested. The program cannot bypass that platform restriction.

## 6. Configure Instagram locally

Instagram publishing requires a Business or Creator account and a Meta app configured for Instagram content publishing/Facebook Login for Business.

Place the numeric Instagram Professional Account ID in `channels.toml`, and put the access token only in `.env`:

```dotenv
UPLOAD_INSTAGRAM=true
INSTAGRAM_ACCESS_TOKEN=your_long_lived_meta_access_token
INSTAGRAM_GRAPH_API_VERSION=v26.0
```

The local program:

1. Creates a resumable `REELS` media container.
2. Uploads the local MP4 to Meta's returned upload URL.
3. Waits for processing to finish.
4. Publishes the container.
5. Retrieves the Reel permalink.
6. Uses `share_to_feed=true`.

Meta controls final visibility and can reject expired tokens, missing permissions, unsupported accounts, or policy-violating media.

## 7. Add YouTube links

Open `links.txt` in VS Code and add one URL per line:

```text
https://www.youtube.com/watch?v=VIDEO_ONE
https://youtu.be/VIDEO_TWO
https://youtube.com/shorts/VIDEO_THREE
```

Save the file. Blank lines and comments beginning with `#` are preserved.

## 8. Start locally from VS Code

### Easiest method

Open **Run and Debug**, select **Run local Shorts automation**, and press **F5**.

### VS Code terminal

```bash
python main.py
```

The watcher prints:

```text
Local watcher started. Add YouTube URLs to links.txt. Press Ctrl+C to stop.
```

It checks `links.txt` every 30 seconds and processes jobs sequentially. You can continue adding links while it runs. Press `Ctrl+C` to stop cleanly.

### Process the current file once

```bash
python -m shorts_bot.file_queue --once
```

Or select **Process links.txt once** in VS Code's Run and Debug menu.

## One-off URL command

To process URLs without editing `links.txt`:

```bash
shorts-cli --platform both "https://youtu.be/VIDEO_ID"
```

Platform overrides:

```bash
shorts-cli --platform youtube "https://youtu.be/VIDEO_ID"
shorts-cli --platform instagram "https://youtu.be/VIDEO_ID"
shorts-cli --platform none "https://youtu.be/VIDEO_ID"
```

`--platform none` creates the MP4 locally without uploading it.

## Configuration reference

| Variable | Default | Purpose |
|---|---:|---|
| `GROQ_API_KEY` | empty | Required Groq API key |
| `GROQ_MODEL` | `llama-3.3-70b-versatile` | Highlight and metadata model |
| `GROQ_TRANSCRIPTION_MODEL` | `whisper-large-v3-turbo` | Timestamped transcription |
| `YTDLP_COOKIES_FROM_BROWSER` | empty | Local signed-in browser cookies for YouTube |
| `YTDLP_BROWSER_PROFILE` | empty | Optional browser profile name/path |
| `CHANNEL_CONFIG_FILE` | `channels.toml` | Local non-secret account IDs |
| `UPLOAD_YOUTUBE` | `false` | Enable YouTube publishing |
| `YOUTUBE_PRIVACY_STATUS` | `public` | Requested YouTube visibility |
| `YOUTUBE_TOKEN_FILE` | `youtube_token.json` | Local OAuth token |
| `UPLOAD_INSTAGRAM` | `false` | Enable Instagram publishing |
| `INSTAGRAM_ACCESS_TOKEN` | empty | Secret local Meta token |
| `INSTAGRAM_GRAPH_API_VERSION` | `v26.0` | Meta Graph API version |
| `LINKS_FILE` | `links.txt` | Local URL queue |
| `DOWNLOADED_LINKS_LOG` | `work/downloaded-links.log` | Download audit log |
| `LINKS_POLL_SECONDS` | `30` | Queue interval, 5–3600 seconds |
| `CLIP_DURATION_SECONDS` | `25` | Preferred duration, 20–30 |
| `WORK_DIR` | `work` | Local media directory |
| `DATABASE_PATH` | `work/jobs.db` | Local SQLite history |
| `KEEP_WORK_FILES` | `true` | Keep local MP4s after publishing |
| `RIGHTS_ACKNOWLEDGED` | `false` | Required rights confirmation |

## Test locally

```bash
python -m pytest -q
python -m ruff check .
```

A VS Code **Run tests** task is included.

## Troubleshooting

### YouTube says "Sign in to confirm you're not a bot"

Sign in to YouTube in your normal local browser, then set that browser in `.env`. For Brave:

```dotenv
YTDLP_COOKIES_FROM_BROWSER=brave
YTDLP_BROWSER_PROFILE=
```

Other supported values include `chrome`, `edge`, and `firefox`. Save `.env`, completely close the
selected browser so Windows releases its cookie database, and retry:

```powershell
python -m shorts_bot.file_queue --once
```

The program asks `yt-dlp` to read the selected browser's existing YouTube cookies locally. It does
not export or commit them. Browser cookies provide account access, so never share or upload them.
If the wrong browser profile is selected, set `YTDLP_BROWSER_PROFILE` to its profile name, such as
`Default` or `Profile 1`.

### YouTube download connection reset on Windows

Update the downloader and retry the same URL:

```powershell
python -m pip install --upgrade yt-dlp
python -m shorts_bot.file_queue --once
```

The workflow resumes partial downloads, forces IPv4, downloads conservatively, and retries temporary
HTTP/CDN failures with exponential backoff. A failed download does not remove its URL from
`links.txt`. If all retries still fail, temporarily disable any VPN/proxy, allow Python through the
firewall or antivirus web shield, or try another network such as a mobile hotspot.

### FFmpeg not found

Install FFmpeg, restart VS Code, and verify `ffmpeg -version` in the integrated terminal.

### YouTube token missing or wrong channel

Run:

```bash
python -m shorts_bot.youtube_auth
```

If the token was created for another channel, delete `youtube_token.json` and authorize again with the correct Google account.

### Instagram upload fails

Confirm that:

- The account is Business or Creator, not a personal account.
- The Meta app has content-publishing permission.
- The token has not expired.
- `channels.toml` contains the Instagram Professional Account ID, not the username.

### A URL disappeared but upload failed

That means the download succeeded and the later step failed. Find the URL in `work/downloaded-links.log`, fix the reported issue, and paste the URL back into `links.txt` to retry.
