# AI Voice Agent — Full Architecture & Flowcharts

A complete, walk-through description of everything built: the concept, the two
architectures, every module, and step-by-step flowcharts of a live call.

---

## 1. The concept in one picture

```
      ☎️ YOU (phone / laptop)                  PERSON 👤
         │      you dial manually                  │
         │ ───────────────────────────────────────▶│  they answer
         │                                         │
         │            two-way call audio           │
         │ ◄───────────────────────────────────────┤
         │                                         │
         ▼                                         │
   [AUDIO BRIDGE]  ⇄  [AI VOICE AGENT]             │
         ▲              │  hear → think → speak    │
         └──────────────┴──────────────────────────┘
```

- **You** start the call. **The AI** takes over and talks the whole conversation.
- The AI is **free**, multilingual, memory-aware, and follows your task.

---

## 2. The two architectures (both built)

### Architecture A — ONE model: Speech-to-Speech (`--sts`)

```
 person audio ──► [ Qwen Omni (one model) ] ──► agent speech audio
                    ├─ understands the speech
                    ├─ reasons about the reply
                    └─ speaks it aloud directly
```
Hosted on a **free Kaggle GPU** (Qwen2.5-Omni-3B, 4-bit). No STT/TTS on your PC.
Best naturalness (tone, pauses, rhythm preserved). Heavier / slower.

### Architecture B — THREE stages (default `main.py`)

```
 person audio → [STT] → text → [LLM] → text → [TTS] → agent audio
                 Groq Whisper     Groq Llama      Edge voices
```
Simple, very fast, one free Groq key. Used for the live-call loopback bridge.

> Both share the SAME controller and memory — you never rebuild anything; pick
> the mode with a CLI flag.

---

## 3. The file map

```
AI_Voice_Agent/
├── gui.py                🖥️ desktop window with START/STOP + audio-source picker
├── main.py               entry point (text / --voice / --call / --sts / --mock)
├── run_channel.py        run the agent on a messaging channel (web/tg/wa/teams/cli)
├── channels/             ★ text messaging layer (WhatsApp, Teams, Telegram, Web)
│   ├── base.py           Channel ABC + per-user sessions + broker
│   ├── broker.py         build/run a channel from config
│   ├── web.py            browser chat (works out of the box)
│   ├── telegram.py       Telegram bot (free, long-polling)
│   ├── whatsapp.py       WhatsApp Business Cloud API webhook
│   └── teams.py          Microsoft Teams Bot Framework endpoint
├── config/
│   ├── config.yaml       ALL settings (providers, audio, phone, memory)
│   └── loader.py         reads config + .env, resolves API keys
├── agent/                ★ the "brain" (pure logic, no model code)
│   ├── controller.py     conversation loop (heart of the system)
│   ├── task.py           task-profile loader + system-prompt builder
│   ├── memory.py         conversation memory + transcript saving
│   └── rules.py          safety guardrails
├── models/               ★ pluggable AI backends
│   ├── base.py           interfaces (STT/LLM/TTS/STS) + factories
│   ├── stt/              speech→text   (groq, openai, deepgram, mock)
│   ├── llm/              text→reply    (groq, openai, gemini, mock)
│   ├── tts/              text→audio    (edge, openai, elevenlabs, mock)
│   └── sts/              audio→audio   (qwen omni/kaggle, mock)
├── audio/                real mic/speaker on your PC
│   ├── input.py          microphone wrapper
│   ├── output.py         speaker wrapper
│   ├── vad.py            voice-activity detection
│   └── streaming.py      mic→VAD→agent→speaker loop (barge-in)
├── phone/                ★ the call-audio bridge
│   ├── bridge.py         AudioBridge interface + factory
│   ├── loopback.py       "you dial, agent talks" virtual-cable bridge
│   ├── connection.py     call session + consent helpers
│   └── README.md         full setup guide
├── tasks/                ★ your teachable "brains"
│   ├── default/          example task
│   └── my_business/      YOUR business template (edit this!)
├── scripts/
│   ├── setup_windows.bat Windows one-time setup
│   ├── run.bat           run helper
│   └── kaggle/           Qwen Omni server (notebook + .py)
├── data/conversations/   saved call transcripts (.jsonl)
└── tests/                offline test suite (10 tests)
```

---

## 4. Flowchart of a full live call (default pipeline + loopback bridge)

This is the whole "you dial, agent talks" flow, end to end:

```
                        ┌─────────────────────────────┐
                        │  main.py --call  (run_call)  │
                        └─────────────┬───────────────┘
                                      │
                                      ▼
                    ┌───────────────────────────────────┐
                    │  Load config + .env keys           │
                    │  Load task = tasks/my_business/     │
                    │  Build Controller (task, STT, LLM,  │
                    │    TTS) via factories               │
                    └──────────────────┬──────────────────┘
                                       ▼
                    ┌───────────────────────────────────┐
                    │  ctrl.start_call()                 │
                    │  • reset memory                   │
                    │  • validate task profile          │
                    │  • speak the OPENING line aloud   │
                    └──────────────────┬──────────────────┘
                                       ▼
        ╔═══════════════════════════════════════════════╗
        ║      LOOP for each person utterance            ║
        ╚═══════════════════════════════════════════════╝
         ┌───────────────────────────────────────────────────┐
         │ 1. LoopbackBridge mic callback gets audio chunk   │
         │ 2. VAD: is there speech?                          │
         │      - silence → keep listening                   │
         │      - speech for ≥350ms → start buffering        │
         │      - ≥800ms silence after speech → SEGMENT done │
         └───────────────────────┬───────────────────────────┘
                                  ▼
         ┌───────────────────────────────────────────────────┐
         │ on_utterance(segment)                             │
         │   encode to WAV → STT (Groq Whisper) → text       │
         └───────────────────────┬───────────────────────────┘
                                  ▼
         ┌───────────────────────────────────────────────────┐
         │ ctrl.handle_utterance(text)                       │
         │  1. detect language  (auto)                       │
         │  2. memory.add(user, text)                        │
         │  3. build system prompt from task (instructions   │
         │     + personality + knowledge + rules + safety)   │
         │  4. LLM.complete(system + recent turns) → reply   │
         │  5. SafetyRules.check(reply)                      │
         │  6. memory.add(assistant, reply)                  │
         └───────────────────────┬───────────────────────────┘
                                  ▼
         ┌───────────────────────────────────────────────────┐
         │ ctrl.speak(reply) → TTS (Edge) → audio bytes      │
         │ LoopbackBridge.speak(audio)                       │
         │   • play into the call's mic input (CABLE Input)  │
         │   • BARGE-IN: if person talks, STOP immediately   │
         │     and go back to listening                      │
         └───────────────────────┬───────────────────────────┘
                                  ▼
                 back to top of loop (next utterance)
                                 │
                                 ▼
                   ┌─────────────────────────────┐
                   │ Ctrl+C → end_call()          │
                   │  transcript saved to         │
                   │  data/conversations/<ts>.jsonl│
                   └─────────────────────────────┘
```

---

## 5. Module-by-module flowcharts

### 5.1 `config/loader.py` — configuration & keys

```
 config/config.yaml ──┐
                      ├──► load_config() ──► merged dict
 .env (GROQ_API_KEY,  ┘        │
 QWEN_URL, ...)                ▼
                        resolve_keys() → {groq, openai, ...}
                              │  reads env var, falls back to config keys
                              ▼
                  passed to the model factories
```

### 5.2 `agent/task.py` — turning your text files into a "brain"

```
tasks/my_business/                          load_task("my_business")
├── instructions.txt   ──┐
├── personality.txt    ──┤
├── rules.txt          ──┼──► TaskProfile ──► system_prompt()
├── opening.txt        ──┤      │  combines:
└── knowledge/         ──┘      ├ ROLE/TASK
    ├── polarion.txt             ├ PERSONALITY
    ├── digital_services.txt     ├ KNOWLEDGE (only this, no inventing)
    ├── ai_services.txt          ├ task RULES
    └── faq.txt                  └ mandatory SAFETY (never human, etc.)
```

### 5.3 `agent/memory.py` — remembering the call

```
 person text ──► memory.add("user", ...) ──► turns[] (list)
 agent reply ──► memory.add("assistant",...)     │
                                                 ├─► context_lines() → last 12
                                                 │    turns sent to the LLM
                                                 ├─► transcript() → full text
                                                 └─► append to
                                                      data/conversations/<ts>.jsonl
```

### 5.4 `models/base.py` — the pluggable interfaces

```
                    ┌───────── STTBase ──► Groq / OpenAI / Deepgram / mock
   interface ──────►├───────── LLMBase ──► Groq / OpenAI / Gemini / mock
   (one abstract    ├───────── TTSBase ──► Edge / OpenAI / ElevenLabs / mock
    class each)     └───────── STSBase ──► Qwen Omni / Kaggle / mock
                           │
    build_stt/llm/tts/sts(cfg, keys)   ← factory picks the class by name
```

### 5.5 `models/sts/` — the Qwen one-model path

```
 your PC                              free Kaggle GPU
 ──────────                          ────────────────
 main.py --sts --audio x.wav         qwen_omni_server.ipynb
      │                                    │
      │ POST /sts  (audio + system +      │  loads Qwen2.5-Omni-3B (4-bit)
      │  history)  ──────────────────►    │  processor → model.generate
      │                                    │  (return_audio=True)
      │ ◄──────── JSON {text, audio_b64,   │
      │            sample_rate}  ──────────┘
      ▼
  reply audio played on your PC
```

---

## 6. The two "hear → think → speak" pipelines side by side

```
   PIPELINE B (default, live call)          PIPELINE A (--sts, Qwen)
 ──────────────────────────────────      ─────────────────────────────
 audio → STT(Groq) → text                audio ─┐
                       → LLM(Groq)→text         Qwen Omni (one model)
                       → TTS(Edge)→audio ←──────┘ understand+reason+speak
 fast, 1 free key                         more natural, heavier
```

Both funnel into the SAME `Controller` so memory, safety, task, and phone
bridging stay identical.

---

## 7. Run modes (all free)

| Command | Does what |
|---------|-----------|
| `python main.py --mock` | Offline text demo, no keys |
| `python main.py` | Live text: Groq + Edge (needs one free Groq key) |
| `python main.py --sts --mock` | One-model path, offline test |
| `python main.py --sts --audio x.wav` | Real Qwen on Kaggle |
| `python main.py --voice` | Mic + speaker on your PC (test loop) |
| `python main.py --call` | **Live phone call** via loopback bridge |
| `python main.py --list-audio` | List audio device ids for the bridge |
| `python tests/test_agent.py` | Run the 10 automated tests |

---

## 8. What's verified vs. what needs your hardware

**Verified here (10/10 tests, real end-to-end runs):**
- Task loading & system-prompt building
- Multilingual: EN / HI / UR / TE / AR all reply in-language
- Memory recall ("What did I say my name was?" → "You said Ahmed")
- Knowledge answers from `about.txt` / `faq.txt`
- Safety rule blocking "I am a human"
- Both `--mock` and `--sts --mock` pipelines
- Loopback **VAD** (segment detection) and **barge-in** logic

**Needs your Windows PC:**
- Real audio (`--voice`, `--call`) — sounddevice + VB-Cable
- Real Qwen (`--sts`) — Kaggle server running
- Actual phone call

---

## 9. Honest limitations

- **Phone network isn't free** — you pay with your call data/plan; the AI is free.
- **Kaggle is best-effort** — free GPU, but sessions time out, tunnel URL changes.
- **No 1B/2B Qwen speech-to-speech** — 3B is the smallest.
- **Real audio/phone untested here** — implemented, verify on Windows hardware.
- **VAD thresholds need tuning** for your mic/cable levels (documented in config).
