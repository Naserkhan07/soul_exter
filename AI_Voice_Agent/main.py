#!/usr/bin/env python3
"""AI Voice Agent — entry point.

Run modes:
  python main.py                       # text REPL (free Groq + Edge stack)
  python main.py --mock                # force ALL providers to mock (fully offline, no keys)
  python main.py --sts                 # Speech-to-Speech (one Qwen Omni model)
  python main.py --sts --audio <file>  # send one real audio turn to a Qwen server
  python main.py --voice               # real microphone + speaker (Windows, audio deps)
  python main.py --call                # live phone call via the configured bridge
  python main.py --task my_business    # pick a task profile (default from config)

Any model can be switched online in config/config.yaml (openai/groq/gemini for
the LLM, openai/deepgram for STT, openai/edge/elevenlabs for TTS) + a .env with
keys. Set every provider to "mock" to run fully offline.
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from config import load_config, resolve_keys
from models import build_stt, build_llm, build_tts, build_sts
from agent import load_task, Controller, ControllerConfig

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
)
log = logging.getLogger("main")

ROOT = Path(__file__).resolve().parent


def build_controller(cfg: dict, mock: bool = False) -> Controller:
    keys = resolve_keys(cfg)
    if mock:
        # Force every provider offline so it runs with zero keys.
        cfg["stt"] = {"provider": "mock"}
        cfg["llm"] = {"provider": "mock"}
        cfg["tts"] = {"provider": "mock"}
    task_name = cfg["agent"].get("task", "my_business")
    task = load_task(task_name, ROOT / "tasks")

    stt = build_stt(cfg.get("stt", {}), keys)
    llm = build_llm(cfg.get("llm", {}), keys)
    tts = build_tts(cfg.get("tts", {}), keys)
    log.info("Providers -> STT: %s | LLM: %s | TTS: %s", stt.name, llm.name, tts.name)
    log.info("Task profile -> %s", task.name)

    cc = ControllerConfig(
        language=cfg["agent"].get("language", "auto"),
        fallback_language=cfg["agent"].get("fallback_language", "en"),
        max_turns=cfg["agent"].get("max_turns", 1000),
        reply_style=cfg["agent"].get("reply_style", "conversational"),
        max_context_turns=cfg.get("memory", {}).get("max_context_turns", 12),
        summarize_after=cfg.get("memory", {}).get("summarize_after", 30),
        persist=cfg.get("memory", {}).get("persist", True),
    )
    return Controller(task, stt, llm, tts, cc, data_dir=ROOT / cfg.get("data", {}).get("dir", "data/conversations"))


def build_sts_controller(cfg: dict, mock: bool = False) -> Controller:
    """Build a controller for the one-model speech-to-speech path."""
    keys = resolve_keys(cfg)
    if mock:
        cfg["sts"] = {"provider": "mock"}
        cfg["tts"] = {"provider": "mock"}
    task_name = cfg["agent"].get("task", "my_business")
    task = load_task(task_name, ROOT / "tasks")
    sts = build_sts(cfg.get("sts", {}), keys)
    # Also keep a TTS so the greeting / opening line can still be spoken even
    # though replies normally come straight from the Qwen STS model as audio.
    tts = build_tts(cfg.get("tts", {}), keys)
    log.info("STS provider -> %s", sts.name)
    cc = ControllerConfig(
        language=cfg["agent"].get("language", "auto"),
        fallback_language=cfg["agent"].get("fallback_language", "en"),
        max_turns=cfg["agent"].get("max_turns", 1000),
        reply_style=cfg["agent"].get("reply_style", "conversational"),
        max_context_turns=cfg.get("memory", {}).get("max_context_turns", 12),
        summarize_after=cfg.get("memory", {}).get("summarize_after", 30),
        persist=cfg.get("memory", {}).get("persist", True),
    )
    return Controller(task, sts=sts, tts=tts, cfg=cc,
                      data_dir=ROOT / cfg.get("data", {}).get("dir", "data/conversations"))


def build_active_controller(cfg: dict, mock: bool = False) -> Controller:
    """Pick the pipeline automatically.

    If a REAL speech-to-speech provider is configured (Qwen on Kaggle / local
    Qwen), use the one-model STS path. Otherwise use the three-stage Groq stack.
    This is what the GUI and --voice/--call use, so switching the 'brain' is
    just a config change (sts.provider + url).
    """
    if not mock and cfg.get("sts", {}).get("provider", "mock").lower() in ("qwen_omni", "qwen_kaggle"):
        return build_sts_controller(cfg, mock)
    return build_controller(cfg, mock)


def process_audio_turn(ctrl: Controller, wav: bytes, sample_rate: int) -> tuple[str, str, bytes, list[str]]:
    """Run one full person-utterance through the active pipeline.

    Returns (person_text, reply_text, reply_audio, lead_changes).
    Works with BOTH pipelines so the GUI / --call / --voice don't care which
    brain is configured.
    """
    if ctrl.uses_sts:
        audio = ctrl.handle_audio(wav)          # Qwen: audio in -> audio out
        users = [t for t in ctrl.memory.turns if t["role"] == "user"]
        assists = [t for t in ctrl.memory.turns if t["role"] == "assistant"]
        person = users[-1]["text"] if users else ""
        reply = assists[-1]["text"] if assists else ""
        return person, reply, audio, ctrl.last_lead_changes
    # Pipeline B: STT -> LLM -> TTS (e.g. Groq + Edge)
    text = (ctrl.stt.transcribe(wav) or "").strip()
    if not text:
        return "", "", b"", []
    reply = ctrl.handle_utterance(text)
    audio = ctrl.speak(reply)
    return text, reply, audio, ctrl.last_lead_changes


def run_text(cfg: dict, mock: bool = False) -> None:
    """Terminal conversation loop (works with ANY provider incl. mock)."""
    ctrl = build_controller(cfg, mock)
    opening = ctrl.start_call()
    print("\n" + "=" * 60)
    print(f"  AI Voice Agent   |   Task: {ctrl.task.name}")
    print("  Type your speech. Commands: /bye /new /lang <code> /tasks /help")
    print("=" * 60)
    if opening:
        print(f"\nAgent: {opening}")

    forced_lang = None
    while True:
        try:
            line = input("\nYou: ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not line:
            continue
        if line.startswith("/"):
            cmd = line[1:].split()
            if cmd[0] in ("bye", "exit", "quit"):
                break
            if cmd[0] == "new":
                ctrl = build_controller(cfg, mock)
                ctrl.start_call()
                print("[new conversation started]")
                continue
            if cmd[0] == "lang":
                forced_lang = cmd[1] if len(cmd) > 1 else None
                ctrl.cfg.language = forced_lang or "auto"
                print(f"[language {'auto' if not forced_lang else forced_lang}]")
                continue
            if cmd[0] == "help":
                print("/bye end | /new reset | /lang <code> force | /tasks list")
                continue
            if cmd[0] == "tasks":
                for p in sorted((ROOT / "tasks").glob("*/")):
                    print("  -", p.name)
                continue
            print("Unknown command:", cmd[0])
            continue

        if ctrl.mock_stt is not None:
            ctrl.mock_stt.set_transcript(line)
            text_in = ctrl.stt.transcribe(b"")
        else:
            # real STT providers expect audio; in text mode we send text directly
            text_in = line

        if ctrl.turn_count() >= ctrl.cfg.max_turns:
            print("\n[max turns reached — ending]")
            break
        reply = ctrl.handle_utterance(text_in)
        print(f"Agent: {reply}")
        audio = ctrl.speak(reply)
        log.info("TTS bytes: %d", len(audio))

    ctrl.end_call()
    print("\n[call saved to data/conversations]")
    print(ctrl.transcript())


def run_sts_text(cfg: dict, mock: bool = False, audio_file: str | None = None) -> None:
    """Speech-to-Speech harness.

    Mock STS (offline): the typed text is treated as the audio the model
    "heard"; the reply text + audio marker are shown.
    Real STS: pass --audio <file.wav> (person's speech) to send one turn to the
    Qwen server, or omit to start an interactive loop.
    """
    if audio_file:
        _process_sts_file(cfg, mock, audio_file)
        return
    ctrl = build_sts_controller(cfg, mock)
    opening = ctrl.start_call()
    print("\n" + "=" * 60)
    print(f"  AI Voice Agent (Speech-to-Speech)  |  Task: {ctrl.task.name}")
    print("  Type speech. Commands: /bye /new /help")
    print("=" * 60)
    if opening:
        print(f"\nAgent: {opening}")

    while True:
        try:
            line = input("\nYou: ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not line:
            continue
        if line.startswith("/"):
            cmd = line[1:].split()
            if cmd[0] in ("bye", "exit", "quit"):
                break
            if cmd[0] == "new":
                ctrl = build_sts_controller(cfg, mock)
                ctrl.start_call()
                print("[new conversation started]")
                continue
            print("Unknown command:", cmd[0])
            continue

        if ctrl.mock_sts is not None:
            ctrl.mock_sts.set_transcript(line)
            audio = ctrl.handle_audio(b"")
            reply = ctrl.memory.turns[-1]["text"]
            print(f"Agent: {reply}")
            log.info("STS audio bytes: %d", len(audio))
        else:
            # Real STS needs an audio file: use --audio <path> per turn
            print("[real STS] pass an audio file with: python main.py --sts --audio <file>")
            break

    ctrl.end_call()
    print("\n[call saved to data/conversations]")
    print(ctrl.transcript())


def _process_sts_file(cfg: dict, mock: bool, audio_file: str) -> None:
    """Send one person audio file to the real Qwen STS server and print result."""
    path = ROOT / audio_file if not Path(audio_file).is_absolute() else Path(audio_file)
    audio = path.read_bytes()
    ctrl = build_sts_controller(cfg, mock)
    ctrl.start_call()
    reply_audio = ctrl.handle_audio(audio)
    last = ctrl.memory.turns[-1]
    print(f"Heard : {ctrl.memory.turns[-2]['text']}")
    print(f"Agent : {last['text']}")
    log.info("Reply audio bytes: %d", len(reply_audio))
    ctrl.end_call()


def run_voice(cfg: dict, mock: bool = False) -> None:
    """Microphone + speaker loop (requires audio deps)."""
    try:
        from audio.streaming import build_engine
    except ImportError as e:  # pragma: no cover
        log.error("Audio mode needs sounddevice+numpy (see requirements-audio.txt). %s", e)
        raise SystemExit(1)

    ctrl = build_controller(cfg, mock)   # run_voice is the Pipeline-B (mic) test
    opening = ctrl.start_call()
    print(f"AI Voice Agent | Task: {ctrl.task.name} | listening... (Ctrl+C to quit)")
    if opening:
        print(f"Agent says: {opening}")
        ctrl.speak(opening)

    def on_utterance(text: str) -> None:
        log.info("Person: %s", text)
        reply = ctrl.handle_utterance(text)
        log.info("Agent: %s", reply)
        ctrl.speak(reply)

    engine = build_engine(on_utterance, cfg.get("audio", {}).get("input", {}))
    engine.start()
    try:
        while True:
            import time
            time.sleep(0.5)
    except KeyboardInterrupt:
        engine.stop()
        ctrl.end_call()


def run_call(cfg: dict, mock: bool = False) -> None:
    """Live phone call via the configured bridge."""
    if cfg.get("phone", {}).get("bridge") == "loopback":
        run_loopback_call(cfg, mock)
        return
    from phone.bridge import build_bridge
    ctrl = build_controller(cfg, mock)
    bridge = build_bridge(cfg)
    bridge.open()
    print("Phone call active (Ctrl+C to end).")
    try:
        while True:
            chunk = bridge.read_audio()
            if not chunk:
                import time
                time.sleep(0.1)
                continue
            text = ctrl.stt.transcribe(chunk)
            if text.strip():
                reply = ctrl.handle_utterance(text)
                audio = ctrl.speak(reply)
                bridge.write_audio(audio)
    except KeyboardInterrupt:
        pass
    finally:
        bridge.close()
        ctrl.end_call()


def list_audio_devices() -> None:
    """Print all audio devices so you can set audio.input.device/output.device."""
    try:
        from phone.loopback import list_devices
    except ImportError:
        print("Needs sounddevice — run: pip install -r requirements-audio.txt")
        return
    print("Available audio devices (set ids in config audio.input.device / output.device):")
    for row in list_devices():
        print(row)


def run_loopback_call(cfg: dict, mock: bool = False) -> None:
    """'You dial, the agent talks' — route your manual call through a virtual
    audio cable into the agent, with VAD + barge-in."""
    from phone.loopback import LoopbackBridge, LoopbackConfig
    from audio.vad import EnergyVAD  # kept for reference; bridge does its own VAD

    ctrl = build_active_controller(cfg, mock)
    opening = ctrl.start_call()
    print("\n" + "=" * 60)
    print("  AI VOICE AGENT — LIVE CALL (loopback bridge)")
    print("  Dial the person now. The agent will take over the conversation.")
    print("  Ctrl+C to end the call.")
    print("=" * 60)
    if opening:
        print(f"Agent says: {opening}")
        ctrl.speak(opening)

    loop_cfg = LoopbackConfig(
        capture_mode=cfg["audio"]["input"].get("capture", "system_loopback"),
        input_device=cfg["audio"]["input"].get("device"),
        output_device=cfg["audio"]["output"].get("device"),
        sample_rate=cfg["audio"]["input"].get("sample_rate", 16000),
        output_sample_rate=cfg["audio"]["output"].get("sample_rate", 24000),
        energy_threshold=cfg["audio"]["vad"].get("energy_threshold", 0.02),
        min_silence_ms=cfg["audio"]["vad"].get("min_silence_ms", 800),
        barge_in=cfg["audio"]["barge_in"].get("enabled", True),
        barge_sensitivity=cfg["audio"]["barge_in"].get("sensitivity", 0.55),
    )

    def on_utterance(segment):
        try:
            wav = _float32_to_wav(segment, loop_cfg.sample_rate)
            person, reply, audio, changes = process_audio_turn(ctrl, wav, loop_cfg.sample_rate)
            if not person:
                log.info("(no speech recognised)")
                return
            log.info("Person: %s", person)
            for c in changes:
                log.info("LEAD: %s", c)
            log.info("Agent: %s", reply)
            if audio:
                _play_into_call(loop_cfg, audio)
            else:
                log.warning("No reply audio returned")
        except Exception as e:  # pragma: no cover
            log.exception("Loopback turn error: %s", e)

    bridge = LoopbackBridge(on_utterance, cfg=loop_cfg)
    bridge.open()
    try:
        while True:
            import time
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        bridge.close()
        ctrl.end_call()


def _float32_to_wav(samples, sample_rate: int) -> bytes:
    """Encode a float32 mono array to 16-bit PCM WAV bytes for STT."""
    import io
    import wave
    import numpy as np
    pcm = (np.clip(samples, -1, 1) * 32767).astype(np.int16).tobytes()
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(pcm)
    return buf.getvalue()


def _play_into_call(loop_cfg, audio_bytes: bytes) -> None:
    """Decode TTS audio (mp3/wav) and play it on the loopback output device."""
    try:
        import soundfile as sf
        import io
        data, sr = sf.read(io.BytesIO(audio_bytes), dtype="float32")
        if data.ndim > 1:
            data = data.mean(axis=1)
        import sounddevice as sd
        with sd.OutputStream(samplerate=sr, channels=1, dtype="float32",
                             device=loop_cfg.output_device) as out:
            out.write(data)
    except Exception as e:  # pragma: no cover
        log.warning("Could not play reply into call: %s", e)


def main() -> None:
    ap = argparse.ArgumentParser(description="AI Voice Agent")
    ap.add_argument("--voice", action="store_true", help="microphone + speaker mode")
    ap.add_argument("--call", action="store_true", help="live phone call via bridge")
    ap.add_argument("--list-audio", action="store_true",
                    help="list available audio devices for the loopback bridge")
    ap.add_argument("--sts", action="store_true",
                    help="speech-to-speech (one Qwen Omni model) mode")
    ap.add_argument("--audio", default=None,
                    help="path to an audio file for the next STS turn (real STS mode)")
    ap.add_argument("--mock", action="store_true",
                    help="force ALL providers to mock (fully offline, no API keys)")
    ap.add_argument("--task", default=None, help="override task profile folder")
    ap.add_argument("--config", default=None, help="path to config.yaml")
    args = ap.parse_args()

    cfg = load_config(args.config)
    if args.task:
        cfg["agent"]["task"] = args.task

    if args.list_audio:
        list_audio_devices()
        return
    if args.call:
        run_call(cfg, args.mock)
    elif args.voice:
        run_voice(cfg, args.mock)
    elif args.sts:
        run_sts_text(cfg, args.mock, args.audio)
    else:
        run_text(cfg, args.mock)


if __name__ == "__main__":
    main()
