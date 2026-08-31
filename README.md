# soul_exter

A **multilingual, real-time AI voice agent** that talks with a person live on a
call — it can explain **what you do** and **what you provide**, follow your
instructions, speak many languages, remember the conversation, and be connected
to a phone. No CRM, no lead-management, no automated business actions.

**You teach the agent by editing plain-text task profiles** — no retraining.

```
AI_Voice_Agent/
└── README.md        ← full docs, quick start, and how to teach your business
```

Get started:

```bash
cd AI_Voice_Agent
python main.py --mock          # fully offline text demo (no keys, no internet)
python main.py --sts --mock    # one-model Speech-to-Speech demo (offline)
python tests/test_agent.py     # run the automated tests
```

**Two free architectures:**
- **Three-stage (default):** put one free Groq key in `.env`, then
  `python main.py` (Groq Whisper + Groq Llama + free Edge voices).
- **Speech-to-Speech (one Qwen Omni model on a free Kaggle GPU):** open
  `AI_Voice_Agent/scripts/kaggle/qwen_omni_server.ipynb` on Kaggle, then
  `python main.py --sts --audio voice.wav`.

See [`AI_Voice_Agent/README.md`](AI_Voice_Agent/README.md) for everything —
modes, model choices (online or mock), multilingual setup, phone bridging, and
the legal note about phone calls.
