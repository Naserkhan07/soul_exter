# AI Voice Agent 🎙️

A **multilingual, real-time voice agent** that talks with a person live on a
call — teaches **what you do** and **what you provide**, remembers the
conversation, and follows your instructions. No CRM, no lead-management, no
automated business actions.

Everything is **modular** and **model-agnostic**:

- The **AI brain** is **Qwen Omni (Speech-to-Speech)** running on a **free
  Kaggle GPU** — one model hears the person and speaks the reply (handles BOTH
  the thinking and the voice). No Groq, no paid provider.
- You **teach the agent** by editing plain-text **task profiles** — no retraining.
- A **phone bridge** connects the same agent to a real phone call.

```
        🎤 MIC / ☎️ PHONE / any app
              │   (system output)
              ▼
   ┌──────────────────────────────┐
   │   Qwen Omni (one model)      │
   │   hears the speech  ────►    │
   │   thinks ──► replies aloud   │
   └──────────────┬───────────────┘
                  │  (reply audio)
              🔊 SPEAKER / ☎️
```

---

## Quick start (Windows)

```bat
setup_windows.bat        :: creates venv, installs deps (one-time)
python run.py            :: 🚀 opens a floating desktop window — click START
python run.py --mock     :: same, but fully offline (no keys, no internet)
python run.py --test     :: run the automated tests
```

That's it — **one command** (`python run.py`) opens a **native floating desktop
window** (this is NOT a web page). Run it from a plain **Command Prompt /
PowerShell terminal** — not from an IDE like VS Code's run button. The window
**stays on top of your other apps** (📌 Always on top is on by default); use
**▭ Compact** to shrink it to a tiny always-on-top live-transcript widget, and
**⤢ Full** to restore. It works no matter which app your call is in (phone,
WhatsApp, Teams, Zoom, Messenger, etc.) because it listens to the **system
audio output** and speaks through your USB/speaker device.

**The window has a START button and an audio-source selector:**
- **"Any app (system)"** → the agent hears whoever is on the call from the
  *system output* (works with any app), and replies through your USB/speaker.
- **"Microphone"** → the agent hears from your *microphone* and replies
  through your speakers (great for testing without a call).

Press **START** → the agent introduces itself (e.g. *"Hi, I'm Naveed"*), says
the task opening, then talks with the person.

The window shows everything live:
- **Live transcript** of both speakers:
  ```
  Agent: Hi, I'm Naveed.
  Agent: We help companies with Polarion and digital services...
  Person: Good morning, I'm Rahul.
  Agent: Good morning Rahul! May I ask what your business works on?
  ...
  ```
- **Lead panel** that fills in as the agent works toward a successful lead —
  Name / Contact / Interest — and shows **🎯 LEAD CAPTURED** when the call has
  all three (the agent is instructed to politely collect name, a contact
  number/email, and their interest, then confirm a follow-up).
- A **STOP** button to end the call.

On Linux/macOS the same commands work with `python3 -m venv venv` first.

---

## Manual steps (do these once on your Windows PC)

1. **Install Python 3.10–3.12** from https://python.org — tick **"Add Python to
   PATH"** during install. *Note: you're on Python 3.14.7 — audio libraries
   (sounddevice/numpy/soundfile) can lag new Python releases, so **3.12 is
   recommended** for the voice/audio parts. The logic runs fine on any version.*
2. **Create the project venv + install deps.** Open a Command Prompt in the
   `AI_Voice_Agent` folder and run:
   ```bat
   scripts\setup_windows.bat
   ```
   (This makes `venv`, installs `requirements.txt` and the audio deps. If you
   prefer by hand: `py -3 -m venv venv` → `venv\Scripts\activate` →
   `pip install -r requirements.txt -r requirements-audio.txt`.)
3. **Point the brain at Qwen on Kaggle (free, no API key).** Start
   `scripts\kaggle\qwen_omni_server.ipynb` on a free Kaggle GPU (T4 x2), copy the
   tunnel URL it prints, and paste it into `config\config.yaml` →
   `sts.qwen_kaggle.url`. This is the ONLY setup step for the AI — no key needed.
4. **Teach the agent YOUR business** — edit `tasks/my_business/` (already
   pre-loaded with the Maqsusi business). See the section below.
5. **Run it:** `python run.py` → press **START**. Choose **"Any app (system)"**
   to talk with a person on any call, or **"Microphone"** to test with your own
   voice.

> **Real voice needs the audio deps + a working mic/speaker.** If audio fails,
> run `python run.py --mock` to test the whole conversation logic with no
> hardware/keys.

### Test it right now (no keys, no GPU)

Run fully offline with zero keys:

```bash
python main.py --mock
```

You'll get an interactive terminal conversation. The agent detects language,
answers from your task knowledge, and remembers names. Try:

```
Hello, who is this?
नमस्ते, आप क्या सेवाएँ देते हैं?        ← replies in Hindi
اس کے بارے میں تھوڑا سمجھائیں          ← replies in Urdu
My name is Ahmed
What did I say my name was?            ← remembers: "You said your name is Ahmed"
/bye
```

Run the automated test suite: `python tests/test_agent.py`

---

## Teach the agent YOUR business (the important part)

You never retrain the AI. You just fill in a **task folder**:

```
tasks/
└── my_business/
    ├── instructions.txt      WHO the agent is + WHAT to do
    ├── personality.txt       TONE (warm, natural, short replies)
    ├── rules.txt             hard rules + safety
    ├── opening.txt           first thing it says on the call
    └── knowledge/
        ├── about.txt         WHAT WE DO / WHAT WE PROVIDE
        └── faq.txt           answers to common questions
```

**To make it talk about YOUR services:** edit `tasks/my_business/` (the
`about.txt` and `faq.txt` placeholders). Save, re-run — the agent is now
"trained" on your business. Create `tasks/<new_name>/` for a different subject
and run `python main.py --task <new_name>`.

---

## The brain — 100% FREE: Qwen Omni on a Kaggle GPU

The **only** brain is **Qwen Omni** running on a **free Kaggle GPU**. One model
hears the person and speaks the reply — it handles both the thinking and the
voice. No Groq, no API keys, no paid provider.

| What | Provider | Key? |
|------|----------|------|
| Think + hear + speak | **Qwen2.5-Omni-3B** (on Kaggle) | No key — just a free Kaggle notebook |
| Greeting voice only | **Microsoft Edge TTS** | No key (free, 100+ voices) |
| Offline test | **mock** (`--mock`) | No keys, no internet |

> Optional fallbacks (only if you ever *don't* want Qwen): the old three-stage
> path still exists with **Gemini** (free tier) or **OpenAI/Deepgram** (paid).
> They are **not** the default and are **not** needed.

**To go live with the free Qwen stack:**
1. Start `scripts/kaggle/qwen_omni_server.ipynb` on Kaggle (**GPU T4 x2**),
   run all cells, and copy the `STS: https://…/sts` URL it prints.
2. Paste it into `config/config.yaml` → `sts.qwen_kaggle.url`.
3. Run `python run.py` → click **START**.

---

## Modes

| Command | What it does |
|---------|--------------|
| `python run.py` | 🚀 **Run the whole project** — opens the app window (click START) |
| `python run.py --mock` | Same, fully offline (no keys, no internet) |
| `python run.py --test` | Run the automated tests |
| `python main.py` | Terminal conversation (mock/optional fallback providers) |
| `python main.py --mock` | Fully offline (mock providers, no keys) |
| `python main.py --sts` | **Speech-to-Speech** (one Qwen Omni model) — test offline with mock |
| `python main.py --sts --audio <file.wav>` | Send one real audio turn to a Qwen Omni server |
| `python main.py --voice` | Microphone + speaker loop (real audio) |
| `python main.py --call` | Live call via the generic system-loopback bridge |
| `python main.py --task <name>` | Use a specific task profile |
| `python tests/test_agent.py` | Run the automated tests |

---

## One brain — Qwen on Kaggle (Speech-to-Speech)

This is the **default and only** brain: a single **Qwen Omni** model takes the
person's audio in and speaks the reply out (no separate STT/LLM/TTS). It runs
on a **free Kaggle GPU**, so your Windows PC does nothing heavy.

> **⚠️ Before it loads, you MUST unlock the model (it's gated).** The error
> `401 Unauthorized` / `Repository Not Found` for `Qwen/Qwen2.5-Omni-3B-Instruct`
> means you haven't done these steps yet:
> 1. **Accept the license:** open https://huggingface.co/Qwen/Qwen2.5-Omni-3B-Instruct,
>    log in, and click **"Agree and access repository"**.
> 2. **Create a read token:** https://huggingface.co/settings/tokens → **New
>    token** (role: **read**) → copy it.
> 3. **Give it to the notebook:** in Kaggle, open **Settings → Secrets → Add a
>    new secret** named `HF_TOKEN` and paste your token. (The notebook also
>    accepts pasting the token directly if no secret is set.)

1. **Start the Kaggle server.** Open `scripts/kaggle/qwen_omni_server.ipynb` in
   Kaggle, set **Accelerator = GPU T4 x2 (16GB)**, and run all cells (the model
   load cell reads your `HF_TOKEN` secret).
2. It loads **Qwen2.5-Omni-3B** (4-bit) and opens a public tunnel, printing:
   `STS: https://xxxx.tunnel.ai/sts`.
3. **Point the agent at it** in `config/config.yaml`:
   ```yaml
   sts:
     provider: "qwen_kaggle"          # default (already set)
     qwen_kaggle:
       url: "https://xxxx.tunnel.ai/sts"   # <-- paste your Kaggle URL here
   ```
4. **Run the whole project** as usual:
   ```bat
   python run.py          :: GUI — click START; Qwen powers the replies
   ```
   (or `python main.py --call`). The GUI/voice/call automatically use Qwen
   whenever a real `sts.provider` is set (the default). The greeting still uses
   free Edge TTS; every reply comes straight from Qwen as audio.

> **Why 3B and not 1B/2B?** Qwen has **no 1B or 2B speech-to-speech model**.
> The smallest native voice-in→voice-out Qwen is **Qwen2.5-Omni-3B**; 4-bit it
> fits a 16GB Kaggle GPU. (`Qwen2.5-Omni-7B` needs ~31GB BF16.) If you truly
> need a <3B model for speech-to-speech you'd use a different family (e.g.
> Gemini-nano-class, or distilled systems) — none are 1B/2B today.

The tunnel URL changes each session, so update `sts.qwen_kaggle.url` whenever
you restart Kaggle. For a stable URL you'd add your own ngrok token (free tier).

The `--sts` flags still work for a quick offline/file test:
`python main.py --sts` (mock) or `python main.py --sts --audio person_speech.wav`.

---

## Multilingual 🌍

Language is **automatic** — you don't choose in advance. Each turn the agent
detects the person's language and replies in it: English, Hindi, Urdu, Telugu,
Arabic, and more (as many as your chosen STT + LLM + TTS support). You can force
a language in text mode with `/lang hi`.

> **Rule of thumb for quality:** Qwen2.5-Omni is natively multilingual
> (English, Hindi, Urdu, Telugu, Arabic and more), so it understands and replies
> in whatever language the person speaks — no per-language setup.

---

## Memory & transcript

- The agent remembers the current call (recent N turns) so it can reference
  earlier context.
- Every call is saved to `data/conversations/<timestamp>.jsonl` (and a `.txt`
  summary), so you can review exactly what was said.

---

## Voice mode & barge-in (Stage 1 milestone)

`--voice` wires mic → VAD → STT → LLM → TTS → speaker, with **barge-in**: if the
person interrupts while the agent is speaking, it stops and listens. Needs
`sounddevice` + `numpy` (see `requirements-audio.txt`).

---

## Calls in any app (generic, not per-platform)

The agent is **platform-agnostic**: it doesn't integrate with WhatsApp/Teams/any
specific app. It just captures whatever the **system is playing** and speaks
through your USB/speaker device. So if you're on a phone call, WhatsApp, Teams,
Zoom or Messenger, the agent hears the person and talks — no per-app setup.

Set the output device in `config.yaml` (`audio.output.device`, find the id with
`python main.py --list-audio`), pick **"Any app (system)"** in the window, press
START.

For a normal phone call the two-way audio goes through a USB audio device / the
laptop's system output; see [`phone/README.md`](phone/README.md) for the bridge
details and free-vs-paid tradeoffs.

---

## Project layout

```
AI_Voice_Agent/
├── run.py                  🚀 ONE command to run the whole project
├── gui.py                  desktop window (START/STOP, transcript, lead panel)
├── main.py                 entry point (text / --voice / --call / --sts)
├── config/config.yaml      providers, languages, audio, keys
├── agent/                  controller, task, memory, rules, lead
├── models/                 pluggable STT / LLM / TTS / STS (+ mock)
├── audio/                  mic, speaker, VAD, streaming engine
├── phone/                  generic audio bridge + connection/consent
├── tasks/                  your teachable "brains"
├── data/conversations/     saved call transcripts
├── tests/                  offline test suite
└── scripts/                Windows setup + run helpers
```

---

## Roadmap (built in stages)

1. ✅ Stage 1 — Listen → think → speak loop (text + mock tests; real audio via `--voice`)
2. ✅ Stage 2 — Task profiles (teach the agent any subject)
3. ✅ Stage 3 — Multilingual automatic detection
4. ✅ Stage 4 — Conversation memory + transcript
5. ✅ Stage 5 — Knowledge retrieval from task files
6. 🔲 Stage 6 — Real-time latency / barge-in tuning (production audio)
7. 🔲 Stage 7 — Phone integration (choose a bridge)

## Legal note

Real phone conversations are subject to consent, recording, and AI-disclosure
laws that differ by country. Make sure your calling setup complies before using
the phone bridge publicly. The project includes an AI-disclosure opening line
you can keep or adjust.
