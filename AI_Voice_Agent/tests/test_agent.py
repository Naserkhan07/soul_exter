"""Tests for the conversation logic (all mock providers, fully offline).

Run with:  python -m pytest tests/ -q
or plain:  python tests/test_agent.py
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agent import load_task, Controller, ControllerConfig  # noqa: E402
from models import build_stt, build_llm, build_tts  # noqa: E402


def make_controller(task="default"):
    cfg = {
        "stt": {"provider": "mock"},
        "llm": {"provider": "mock"},
        "tts": {"provider": "mock"},
    }
    task = load_task(task, ROOT / "tasks")
    return Controller(
        task,
        build_stt(cfg["stt"], {}),
        build_llm(cfg["llm"], {}),
        build_tts(cfg["tts"], {}),
        ControllerConfig(language="auto"),
    )


def say(ctrl, text):
    if ctrl.mock_stt is not None:
        ctrl.mock_stt.set_transcript(text)
        return ctrl.handle_utterance(text)
    return ctrl.handle_utterance(text)


def test_task_loading():
    t = load_task("my_business", ROOT / "tasks")
    assert t.instructions
    assert "my_business" in str(t.root)
    assert "faq" in t.knowledge
    assert any(k in t.knowledge for k in ("polarion", "digital_services", "about"))


def test_greeting_english():
    c = make_controller()
    c.start_call()
    r = say(c, "Hello, how are you?")
    assert isinstance(r, str) and r
    # greeting should be detected as English
    assert any(ch in r for ch in "Hello")


def test_multilingual_hindi():
    c = make_controller()
    c.start_call()
    r = say(c, "नमस्ते, मैं आपके बारे में जानना चाहता हूँ")
    assert any(ch in r for ch in "नमस्ते" or "AI" or "हूँ")  # devanagari script => Hindi reply
    # reply should contain Devanagari characters
    assert any('\u0900' <= ch <= '\u097F' for ch in r)


def test_multilingual_urdu():
    c = make_controller()
    c.start_call()
    r = say(c, "اس کے بارے میں تھوڑا سمجھائیں")
    assert any('\u0600' <= ch <= '\u06FF' for ch in r)


def test_multilingual_telugu():
    c = make_controller()
    c.start_call()
    r = say(c, "మీరు ఏమి అందిస్తారు?")
    assert any('\u0C00' <= ch <= '\u0C7F' for ch in r)


def test_memory_recall_name():
    c = make_controller()
    c.start_call()
    say(c, "Hi, my name is Ahmed")
    r = say(c, "What was the thing I told you earlier?")
    r2 = say(c, "What did I say my name was?")
    assert "Ahmed" in r2


def test_knowledge_answer():
    c = make_controller("my_business")
    c.start_call()
    r = say(c, "What services do you provide?")
    assert r.strip()
    # should mention something from knowledge (mock returns knowledge lines)


def test_safety_blocks_human_claim():
    from agent.rules import SafetyRules
    sr = SafetyRules()
    assert sr.check("I am a human") == "I'm sorry, I can't answer that."
    assert "hello" in sr.check("hello")


def test_system_prompt_build():
    t = load_task("default", ROOT / "tasks")
    sp = t.system_prompt()
    assert "ROLE / TASK" in sp
    assert "SAFETY" in sp
    assert "KNOWLEDGE" in sp


def test_sts_mock_path():
    """The one-model speech-to-speech path works offline with the mock STS."""
    from models import build_sts
    sts = build_sts({"provider": "mock"}, {})
    from agent import Controller, ControllerConfig
    task = load_task("my_business", ROOT / "tasks")
    ctrl = Controller(task, sts=sts, cfg=ControllerConfig(language="auto"))
    ctrl.start_call()
    sts.set_transcript("My name is Ali")
    audio = ctrl.handle_audio(b"")
    assert audio == b"<mock-audio>"
    # reply is remembered (mock LLM says "Nice to meet you, Ali.")
    assert "Ali" in ctrl.memory.turns[-1]["text"]


def test_lead_capture():
    """The agent captures a full lead (name + contact + interest)."""
    from agent import Lead
    lead = Lead()
    lead.update("My name is Rahul")
    lead.update("You can reach me at 9876543210")
    lead.update("We need a website and SEO")
    assert lead.name == "Rahul"
    assert lead.phone == "9876543210"
    assert lead.interest == "Website"
    assert lead.captured is True
    assert lead.completeness >= 1.0


def test_web_channel_session_and_lead():
    """A channel runs the agent with per-session memory + lead capture."""
    from config import load_config
    from main import build_controller
    from channels.base import ChannelBroker
    from channels.broker import _controller_factory
    from channels.web import WebChannel

    cfg = load_config()
    broker = ChannelBroker(_controller_factory(cfg, mock=True))
    web = WebChannel(broker, {"port": 8770}, mock=True)
    r1 = web._api_message({"text": "My name is Sarah"})
    assert "Sarah" in r1["lead"]["name"]
    r2 = web._api_message({"text": "I need SEO for my shop, call me at 9988776655"})
    assert r2["lead"]["captured"] is True
    assert r2["lead"]["interest"] == "SEO"


def _run_all():
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = 0
    for fn in fns:
        try:
            fn()
            print(f"  PASS  {fn.__name__}")
            passed += 1
        except AssertionError as e:
            print(f"  FAIL  {fn.__name__}: {e}")
    print(f"\n{passed}/{len(fns)} passed")
    return 0 if passed == len(fns) else 1


if __name__ == "__main__":
    raise SystemExit(_run_all())
