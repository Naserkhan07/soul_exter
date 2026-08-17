# Local Groq Shorts + Instagram Reels Automation

This project runs entirely on your laptop from VS Code. There is no Telegram bot, web server, cloud worker, or Docker requirement.

Add authorized YouTube links to `links.txt`. The local program downloads each video, removes its link after a successful download, divides the usable timeline into consecutive 20–30 second clips based on the video's duration, generates detailed AI metadata and thumbnails, renders vertical Shorts, and publishes each one to YouTube and Instagram.

> **Only process videos you own or have explicit permission/license to download, edit, and republish.** A publicly viewable video is not automatically licensed for reuse. The program requires `RIGHTS_ACKNOWLEDGED=true`.

## What the local workflow does

1. Watches the local `links.txt` file.
2. Downloads one authorized YouTube video at a time using the Python API equivalent of `yt-dlp -f "bestvideo+bestaudio" URL`, then remuxes those streams without source re-encoding.
3. Removes every matching URL line immediately after the video downloads successfully.
4. Records the URL and job ID in `work/downloaded-links.log`.
5. Extracts speech audio locally with FFmpeg.
6. Uses Groq `whisper-large-v3-turbo` for timestamped transcription.
7. In `full_coverage` mode, calculates the clip count from source duration and covers the timeline with consecutive 20–30 second sections.
8. Generates a detailed YouTube title/description and a separate Instagram caption for every clip.
9. Renders every section as an H.264/AAC MP4 at the configured native-resolution policy.
10. When enabled, temporarily hosts selected clips and runs API.market Real-ESRGAN before upload.
11. Generates a JPEG thumbnail from the final (enhanced or original) clip.
12. Uploads every result as a public YouTube Short and an Instagram Reel, using a custom YouTube thumbnail when the channel is eligible and a midpoint cover frame on Instagram.

A downloaded URL is removed before AI/render/upload starts. If a later stage fails, the URL remains in `work/downloaded-links.log`; copy it back into `links.txt` when you want to retry.

## Local files

- `main.py` — easiest way to start the watcher from VS Code
- `links.txt` — paste one YouTube URL per line
- `channels.toml` — non-secret YouTube and Instagram account IDs
- `.env` — local API keys and tokens; never committed
- `client_secret.json` — Google OAuth desktop client; never committed
- `youtube_token.json` — generated Google OAuth token; never committed
- `work/jobs.db` — local job history
- `work/jobs/<job-id>/short-001.mp4`, `short-002.mp4`, … — rendered Shorts/Reels
- `work/jobs/<job-id>/thumbnail-001.jpg`, `thumbnail-002.jpg`, … — generated covers
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

The Python installation command also installs the Deno JavaScript runtime and `yt-dlp-ejs` inside
`.venv`. Current YouTube player challenges require these components for normal format availability;
no separate global Deno installation is needed.

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
GROQ_MODEL=llama-3.1-8b-instant
GROQ_FALLBACK_MODEL=llama-3.1-8b-instant
GROQ_TRANSCRIPTION_MODEL=whisper-large-v3-turbo
GROQ_MAX_TRANSCRIPT_CHARS=8000
GROQ_METADATA_DELAY_SECONDS=30
YOUTUBE_DESCRIPTION_TARGET_CHARS=4200
INSTAGRAM_CAPTION_TARGET_CHARS=2000
INSTAGRAM_HASHTAGS_FILE=instagram_hashtags.txt
CLIP_DURATION_SECONDS=30
SHORTS_SELECTION_MODE=full_coverage
MAX_SHORTS_PER_VIDEO=0
VIDEO_LAYOUT=center_crop
VIDEO_ALLOW_UPSCALE=false
VIDEO_CRF=18
VIDEO_PRESET=slow
RIGHTS_ACKNOWLEDGED=true
```

`MAX_SHORTS_PER_VIDEO=0` means automatic duration-based counting. A 10-minute source produces 20
30-second clips. The workflow distributes unusually short remainders where possible; the unavoidable
platform ceiling is 100 clips per source because both YouTube and Instagram limit automated daily
publishing. Set a positive value only when you intentionally want a lower cap.

The source is downloaded and transcribed once. After that, clips stream through the workflow one at
a time: generate metadata for clip 1 → render clip 1 → upload clip 1 to both platforms → continue to
clip 2. It never waits for metadata or rendering of the entire batch before the first upload.

No OpenAI API key or OpenAI service is used. The automatic workflow keeps Groq as its hosted AI
backend so no model is downloaded to the laptop. Kaggle notebooks are useful for interactive or
batch GPU experiments, but their sessions are temporary and do not provide a dependable always-on
API for this unattended local queue; using a tunneled notebook would stop whenever the Kaggle
session ends.

Detailed metadata is generated in a separate paced Groq request for every selected clip. The
configured 4,200-character YouTube and 2,000-character Instagram values are maximum targets, not
forced filler lengths. Metadata expands when the transcript contains enough factual information and
stays shorter when a 30-second clip cannot support more detail. One automatic repair request runs for
very short responses, but the clip is never blocked merely for being concise. Instagram accepts at
most 30
hashtags per caption, so the entire supplied hashtag list cannot appear on every Reel. The full
editable pool is stored in `instagram_hashtags.txt`; groups of 30 unique tags rotate across the Reel
batch while every caption remains within the platform limit.

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

## 7. Optional API.market Real-ESRGAN enhancement

API.market requires `video_path` to be a direct public HTTPS URL; it cannot read a Windows file path.
The workflow therefore uploads each selected local clip temporarily to Cloudinary, submits that URL
to API.market, polls the asynchronous prediction, downloads the enhanced MP4, deletes the temporary
Cloudinary input, generates the thumbnail from the enhanced result, and only then uploads to YouTube
and Instagram.

Any key visible in a screenshot or chat is compromised. Revoke it and put only the replacement in
the gitignored `.env` file. Create a Cloudinary account and configure:

```dotenv
VIDEO_ENHANCER=api_market
APIMARKET_API_KEY=YOUR_NEW_ROTATED_KEY
APIMARKET_MODEL=RealESRGAN_x4plus
APIMARKET_RESOLUTION=FHD
APIMARKET_MAX_CLIPS=5
APIMARKET_TIMEOUT_SECONDS=1200

CLOUDINARY_CLOUD_NAME=YOUR_CLOUD_NAME
CLOUDINARY_API_KEY=YOUR_CLOUDINARY_API_KEY
CLOUDINARY_API_SECRET=YOUR_CLOUDINARY_API_SECRET
```

`APIMARKET_MAX_CLIPS=5` enhances only clips 1–5 as selected for the initial trial. Set it to `0` only
when the account has enough paid units to enhance every clip. Each enhanced clip consumes a separate
prediction. The temporary hosting object is deleted in cleanup even when enhancement fails.

## 8. Add YouTube links

Open `links.txt` in VS Code and add one URL per line:

```text
https://www.youtube.com/watch?v=VIDEO_ONE
https://youtu.be/VIDEO_TWO
https://youtube.com/shorts/VIDEO_THREE
```

Save the file. Blank lines and comments beginning with `#` are preserved.

## 9. Start locally from VS Code

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

If a downloaded job later fails during AI, rendering, or upload, retry it without downloading again:

```bash
python -m shorts_bot.file_queue --resume JOB_ID
```

A job created before multi-clip support keeps its already-published single Short when resumed. To
reuse its downloaded source and create a new multi-clip batch, run:

```bash
python -m shorts_bot.file_queue --expand JOB_ID
```

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
| `GROQ_MODEL` | `llama-3.1-8b-instant` | Token-efficient highlight/metadata model |
| `GROQ_FALLBACK_MODEL` | `llama-3.1-8b-instant` | Used if the primary model is rate-limited |
| `GROQ_TRANSCRIPTION_MODEL` | `whisper-large-v3-turbo` | Timestamped transcription |
| `GROQ_MAX_TRANSCRIPT_CHARS` | `8000` | Sampled planning transcript budget |
| `GROQ_METADATA_DELAY_SECONDS` | `30` | Pacing between detailed per-clip metadata calls |
| `YOUTUBE_DESCRIPTION_TARGET_CHARS` | `4200` | Target detailed description length, max 4500 |
| `INSTAGRAM_CAPTION_TARGET_CHARS` | `2000` | Caption limit including hashtags, max 2000 |
| `INSTAGRAM_HASHTAGS_FILE` | `instagram_hashtags.txt` | Editable pool rotated in groups of 30 |
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
| `CLIP_DURATION_SECONDS` | `30` | Preferred duration, 20–30 |
| `SHORTS_SELECTION_MODE` | `full_coverage` | `full_coverage` or `ai_highlights` |
| `MAX_SHORTS_PER_VIDEO` | `0` | `0` = duration-based automatic count; 1–100 = optional cap |
| `VIDEO_LAYOUT` | `center_crop` | Full-frame crop with no blurred bars; optional `blurred_background` |
| `VIDEO_ALLOW_UPSCALE` | `false` | Keep native crop dimensions instead of enlarging pixels |
| `VIDEO_CRF` | `18` | x264 quality; lower is higher quality/larger |
| `VIDEO_PRESET` | `slow` | x264 compression preset |
| `VIDEO_ENHANCER` | `none` | Set `api_market` to enable remote Real-ESRGAN |
| `APIMARKET_API_KEY` | empty | Rotated private API.market key |
| `APIMARKET_MODEL` | `RealESRGAN_x4plus` | Remote enhancement model |
| `APIMARKET_RESOLUTION` | `FHD` | Requested output resolution |
| `APIMARKET_MAX_CLIPS` | `5` | First N clips enhanced; `0` means all |
| `CLOUDINARY_CLOUD_NAME` | empty | Temporary input hosting account |
| `CLOUDINARY_API_KEY` | empty | Temporary input hosting key |
| `CLOUDINARY_API_SECRET` | empty | Temporary input hosting secret |
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

### Groq daily token limit reached

The project defaults to `llama-3.1-8b-instant`, whose free daily token allowance is larger than the
70B model's allowance. Long transcripts are compacted into contiguous candidate blocks sampled
across the full timeline before planning. If an existing `.env` still selects the 70B model, use:

```dotenv
GROQ_MODEL=llama-3.1-8b-instant
GROQ_FALLBACK_MODEL=llama-3.1-8b-instant
GROQ_MAX_TRANSCRIPT_CHARS=8000
```

A URL is removed after download by design. If AI planning then fails, reuse the local source without
redownloading it:

```powershell
python -m shorts_bot.file_queue --resume JOB_ID
```

Use the job ID printed in brackets in the failure output. If the 8B model's limit is also exhausted,
wait until Groq's reported reset time or upgrade the Groq service tier.

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

### YouTube says "Requested format is not available"

Current YouTube downloads require an external JavaScript runtime and EJS challenge scripts. Pull the
latest update and reinstall the project; its `yt-dlp[default,deno]` dependency installs Deno and
`yt-dlp-ejs` inside `.venv`. The downloader also falls back to any available video/audio codecs and
uses FFmpeg to produce the final MP4.

```powershell
git pull origin arena/01a00af0-soul-exter
python -m pip install --upgrade "yt-dlp[default,deno]"
python -m pip install -e ".[dev]"
deno --version
python -m shorts_bot.file_queue --once
```

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

### Uploaded video looks blurry

First wait for YouTube and Instagram to finish HD processing; immediately after upload they may only
serve a low-resolution rendition. The default renderer fills the frame with a native-resolution 9:16
center crop—there are no blurred bars and no enlargement. It preserves the source frame rate and
encodes H.264 at CRF 18 with the slow preset. Confirm `.env` contains:

```dotenv
VIDEO_LAYOUT=center_crop
VIDEO_ALLOW_UPSCALE=false
VIDEO_CRF=18
VIDEO_PRESET=slow
```

The downloader keeps yt-dlp's highest available source streams without AI enhancement. For Shorts,
FFmpeg must still crop the source to 9:16 and re-encode the selected time range, but with upscaling
disabled it preserves the crop's native pixel dimensions instead of stretching it to 1080×1920.
A 360p or 480p source therefore stays low resolution but does not receive invented/upscaled pixels.
Existing rendered/uploaded files are not changed by a configuration update. To reuse the downloaded
source, re-render all tracked clips with current settings, and upload new copies, run:

```powershell
python -m shorts_bot.file_queue --rebuild JOB_ID
```

The old platform posts remain online and must be deleted manually after checking the replacements.
`--rebuild` now removes every stale `short-*.mp4` and thumbnail before starting, resets metadata so
long descriptions/captions are regenerated, and validates any existing MP4 before reuse. This avoids
`moov atom not found` failures caused by interrupted partial files.

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
- `channels.toml` contains the numeric `instagram_business_account.id`, not the username,
  Facebook Page ID, or Business Portfolio name. Retrieve it with:
  `/me/accounts?fields=id,name,instagram_business_account{id,username},access_token`.

### A URL disappeared but a later stage failed

That means the download succeeded. Fix the reported AI, rendering, token, or upload issue and resume
using the job ID printed in the terminal:

```powershell
python -m shorts_bot.file_queue --resume JOB_ID
```

Completed clips and platform uploads are recorded individually, so a resume skips successful clips
and does not repost them. Instagram's official Content Publishing API permits at most 100
API-published posts per rolling 24 hours. YouTube custom thumbnail eligibility varies by channel;
if `thumbnails.set` is refused, the video remains published and YouTube uses its generated frame.
