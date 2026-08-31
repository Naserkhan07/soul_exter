# Phone Bridge — getting live two-way audio into the AI

The AI itself is phone-agnostic: it just needs **audio in** (the person's
speech) and **audio out** (the agent's speech). The *phone bridge* decides
WHERE that two-way audio comes from.

> ⚠️ Honest truth: the **AI is free**, but the **telephone network itself is
> never free**. So the free way to place calls is the "you dial, the agent
> talks" workflow below, which uses YOUR phone/laptop data for the call and a
> free virtual audio cable to route the audio.

---

## ✅ RECOMMENDED: the free "you dial, the agent talks" workflow (loopback)

This is exactly what you described — **no virtual cable needed**:

```
 PERSON speaks on the call
      │
      │  call audio plays through the laptop's SYSTEM output
      ▼
 [AI VOICE AGENT]  ◄── SYSTEM LOOPBACK capture  (hears the person)
      │
      │  replies
      ▼
 [USB AUDIO DEVICE]  ── USB cable ──►  PHONE  ──►  PERSON hears the agent
```

- **HEAR the person** → the agent records the **system output** (WASAPI
  loopback), i.e. the person's voice that your call app plays through the
  laptop. No VB-Cable.
- **SPEAK to the person** → the agent's reply plays out a **USB audio device**
  connected to your phone via a USB cable, so the person on the call hears it.

### Step-by-step (Windows)

1. **Install deps**
   ```bat
   pip install -r requirements-audio.txt
   ```
   (`soundcard` is what powers the system-loopback capture.)
2. **Connect your phone to the PC via USB** so it shows up as an audio device
   (a USB audio interface / DAC, or the phone's USB-audio mode).
3. **Find your audio device ids**
   ```bat
   python main.py --list-audio
   ```
   Find the id of the **USB output device** that goes to your phone.
4. **Set the config** in `config/config.yaml`:
   ```yaml
   audio:
     input:
       capture: "system_loopback"   # hears the person from system output
       sample_rate: 16000
     output:
       device: <USB device id>      # agent speaks to the phone via USB
       sample_rate: 24000
   phone:
     bridge: "loopback"
   ```
   (`capture: "system_loopback"` is the default — no device id needed for input.)
5. **Start the agent**
   ```bat
   python main.py --call
   ```
6. **Dial the person.** The agent will greet them, listen, think, and reply —
   with VAD (knows when they've finished talking) and barge-in (stops if they
   interrupt).

> Tip: monitor the agent's console — it prints what it "hears" and its replies,
> so you can confirm the audio routing is correct before a real call.

> ⚠️ Avoid self-hearing: because the agent captures the SYSTEM output, make sure
> the agent's own reply goes only to the USB device (phone), not to the same
> system speakers it is listening to — otherwise it would hear itself and
> barge-in on its own speech.

---

## Other options (for reference)

| Option | Cost | Effort | Notes |
|--------|------|--------|-------|
| **Loopback (system + USB)** (above) | Free | Medium | You dial manually; best free route |
| **Physical audio interface** | Free (if you own the gear) | High | Phone → USB coupler → PC |
| **VoIP / SIP softphone** | Low/zero | Medium | Pipe SIP RTP audio to the AI |
| **Twilio Media Streams** | Paid/min | Low | Easiest, reliable, but billed per minute |

### Physical audio interface
```
PHONE  ⇄  COUPLER / USB AUDIO INTERFACE  ⇄  PC (mic-in / speaker-out)  ⇄  AI
```
`phone.bridge: audio`. No telephony API fees, but needs hardware and call audio
quality depends on the coupler.

### Cloud telephony (paid)
`phone.bridge: twilio` — live websocket audio. Add `TWILIO_ACCOUNT_SID`,
`TWILIO_AUTH_TOKEN`, `TWILIO_FROM_NUMBER` in `.env`. Billed per minute.

---

## Architecture

```
             ┌─────────────────────────────────────────────┐
  TELEPHONE  │   phone bridge (phone/loopback.py)          │  AI
  network ──▶│  in: person speech ──▶ STT ──▶ LLM ──▶ TTS  │──▶ phone
             │  out: agent voice  ◀── bridge.speak()       │
             └─────────────────────────────────────────────┘
```

`phone/loopback.py` is a streaming bridge: it runs VAD on the person's audio,
fires an `on_utterance` callback with the speech segment, and plays the agent's
reply with barge-in. The controller at `agent/controller.py` never knows whether
it's talking to a mic, a phone bridge, or a terminal — that design keeps the AI
reusable.

---

## Consent & disclosure (please read)

Phone calls are regulated. Before going live with the public network, confirm
your local rules on:
- **Recording consent** (one-party vs two-party jurisdictions),
- **AI disclosure** (announcing the caller is an AI assistant),
- **Do-not-call / telemarketing** rules for the calls you're making.

The agent's `opening.txt` and `phone/connection.py` include an AI-disclosure +
recording reminder you can keep or adjust to fit your legal obligations.
