# AI Voice Agent 🎙️

A **multilingual, real-time voice agent** that talks with a person live on a
call — teaches **what you do** and **what you provide**, remembers the
conversation, and follows your instructions. No CRM, no lead-management, no
automated business actions.

Everything is **modular** and **model-agnostic**:

- The **AI brain** runs on **online** speech/LLM providers (works on any laptop,
  or an online GPU like Kaggle — no local GPU needed), and there's a fully
  offline **mock** mode to test the whole logic with zero setup.
- You **teach the agent** by editing plain-text **task profiles** — no retraining.
- A **phone bridge** connects the same agent to a real phone call.

```
        🎤 MIC / ☎️ PHONE
              │
              ▼
   ┌──────────────────────┐
   │   STT  (understand)  │
   │   LLM  (reason)      │
   │   TTS  (speak)       │
   └──────────┬───────────┘
              │
         🔊 SPEAKER / ☎️
```

---

## Quick start (Windows)

```bat
setup_windows.bat        :: creates venv, installs deps
python gui.py            :: 🖥️ GUI window with a START button (recommended)
python main.py           :: text test — uses the free Groq + Edge stack
python main.py --mock    :: fully offline test — no keys, no internet needed
python main.py --voice   :: real microphone + speaker
```

**The GUI is the easy way to go live:** a window opens with a **START** button
and an **audio-source** selector.

- Choose **"Phone (USB)"** → the agent hears the person from your *system
  output* and replies through your **USB device** to the phone.
- Choose **"Laptop (mic)"** → the agent hears from your *microphone* and
  replies through your speakers.

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

## Choose your models — 100% FREE stack (from config.yaml)

Everything defaults to free providers. The only thing you need is **one free
Groq key** (for listening + thinking); speaking uses **Microsoft Edge TTS**
which needs no key at all.

| Component | FREE default | Notes |
|-----------|--------------|-------|
| Listen (STT) | **Groq `whisper-large-v3`** | free tier, fast, multilingual |
| Reason (LLM) | **Groq `llama-3.3-70b-versatile`** | free tier, very fast |
| Speak (TTS)  | **Microsoft Edge TTS** | 100% free, no key, 100+ voices (hi/ur/ar/te…) |
| Offline test | **mock** (`--mock`) | no keys, no internet |

> A free alternative for the LLM is **Gemini `gemini-1.5-flash`** (Google free
> tier). The paid providers (OpenAI, Deepgram, ElevenLabs) are still available
> in the code but are **not** used by default — just switch the `provider` line
> in `config/config.yaml` if you ever want them.

To go live with the free stack:
1. Copy `.env.example` → `.env`, paste your free `GROQ_API_KEY`
   (get it at https://console.groq.com/keys).
2. `pip install -r requirements.txt` (installs `edge-tts`).
3. Run `python main.py`.

---

## Modes

| Command | What it does |
|---------|--------------|
| `python gui.py` | 🖥️ Desktop window: START/STOP, live transcript, lead-capture panel |
| `python main.py` | Terminal conversation (free Groq + Edge stack) |
| `python main.py --mock` | Fully offline (mock providers, no keys) |
| `python main.py --sts` | **Speech-to-Speech** (one Qwen Omni model) — test offline with mock |
| `python main.py --sts --audio <file.wav>` | Send one real audio turn to a Qwen Omni server |
| `python main.py --voice` | Microphone + speaker loop (real audio) |
| `python main.py --call` | Live phone call through the configured bridge |
| `python main.py --task <name>` | Use a specific task profile |
| `python tests/test_agent.py` | Run the automated tests |

---

## Two architectures (pick one)

This project supports BOTH designs from your original spec.

**Pipeline A — Speech-to-Speech, one model (`--sts`)**
Your preferred architecture: a single Qwen Omni model takes the person's audio
in and speaks the reply out (no separate STT/LLM/TTS). Hosted on a free Kaggle
GPU so your PC does nothing heavy. See [the Kaggle guide below](#-kaggle-speech-to-speech-qwen-omni).

**Pipeline B — three stages (default `main.py`)**
`STT → LLM → TTS` with the free online stack (Groq + Edge). Simpler to run,
one free key.

You don't rebuild anything — the controller handles both. Pick with the flag.

---

## 🔥 Kaggle Speech-to-Speech (Qwen Omni) — free GPU

This is the "one model" idea, run on a **free Kaggle GPU** so your PC has no
heavy AI and no Python speech latency.

1. Open `scripts/kaggle/qwen_omni_server.ipynb` in Kaggle, set
   **Accelerator = GPU T4 x2 (16GB)**, and run all cells.
2. It loads **Qwen2.5-Omni-3B** (4-bit) and opens a public tunnel, printing:
   `STS: https://xxxx.tunnel.ai/sts`.
3. Put that URL in `config/config.yaml` → `sts.qwen_kaggle.url`.
4. On your PC: `python main.py --sts --audio person_speech.wav`.

> **Why 3B and not 1B/2B?** Qwen has **no 1B or 2B speech-to-speech model**.
> The smallest native voice-in→voice-out Qwen is **Qwen2.5-Omni-3B**; 4-bit it
> fits a 16GB Kaggle GPU. (`Qwen2.5-Omni-7B` needs ~31GB BF16.) If you truly
> need a <3B model for speech-to-speech you'd use a different family (e.g.
> Gemini-nano-class, or distilled systems) — none are 1B/2B today.

The tunnel URL changes each session, so update the config whenever you restart
Kaggle. For a stable URL you'd add your own ngrok token (free tier).

---

## Multilingual 🌍

Language is **automatic** — you don't choose in advance. Each turn the agent
detects the person's language and replies in it: English, Hindi, Urdu, Telugu,
Arabic, and more (as many as your chosen STT + LLM + TTS support). You can force
a language in text mode with `/lang hi`.

> **Rule of thumb for quality:** your STT, LLM, and TTS should all support the
> languages you care about. The free stack (Groq Whisper + Groq Llama + Edge
> TTS) already covers English, Hindi, Urdu, Telugu, Arabic and many more.

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

## Phone calls

The AI and the phone are **separate layers**. `--call` uses an audio bridge so
the agent consumes live two-way call audio. Details, options (physical audio
interface vs. VoIP/SIP vs. Twilio), and the free-vs-paid tradeoffs are in
[`phone/README.md`](phone/README.md).

---

## Project layout

```
AI_Voice_Agent/
├── main.py                 entry point (text / --voice / --call)
├── config/config.yaml      providers, languages, audio, keys
├── agent/                  controller, task, memory, rules
├── models/                 pluggable STT / LLM / TTS (+ mock)
├── audio/                  mic, speaker, VAD, streaming engine
├── phone/                  audio bridge + connection/consent
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
