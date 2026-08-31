#!/usr/bin/env python3
"""AI Voice Agent — floating overlay desktop window.

This is a NATIVE desktop window (not a web page). Open it from a plain Command
Prompt / PowerShell terminal — NOT from an IDE such as VS Code's "run" button —
with:

    python run.py            # opens this window (Qwen on Kaggle + Edge greeting)
    python run.py --mock     # fully offline (no keys, no internet)

The window is a small floating overlay that stays on top of your other apps
(📌 Always on top is ON by default). Use ▭ Compact to shrink it into a tiny
live-transcript widget, and ⤢ Full to restore.

When you press START the agent introduces itself ("Hi, I'm Naveed"), says the
task opening, then talks with the person on the call — whether they're on your
laptop (mic/speaker) or on a phone connected by USB cable.

Audio source is chosen in the window:
    * "Any app (system)" -> hears the person from whatever the SYSTEM is
                            playing (phone call, WhatsApp, Teams, Zoom,
                            Messenger...), replies through your USB/speaker
                            device. Generic — works with any app.
    * "Microphone"       -> hears the person from your microphone, replies
                            through your speakers.
"""

from __future__ import annotations

import argparse
import logging
import queue
import threading
from pathlib import Path

from config import load_config
from main import build_active_controller, process_audio_turn, ROOT
from phone.loopback import LoopbackBridge, LoopbackConfig, decode_audio_to_float32

logging.basicConfig(level=logging.INFO, format="%(levelname)-7s %(name)s: %(message)s")
log = logging.getLogger("gui")


class VoiceAgentGUI:
    def __init__(self, root, cfg: dict, mock: bool = False, source: str | None = None):
        import tkinter as tk
        from tkinter import ttk

        self.root = root
        self.cfg = cfg
        self.mock = mock
        self.tk = tk
        self.ttk = ttk
        self._source = source
        self.ctrl = None
        self.bridge = None
        self.running = False
        self.worker = None
        self._ui_q: queue.Queue = queue.Queue()
        self._lead_shown = set()

        root.title("AI Voice Agent")
        root.geometry("720x560")
        root.configure(bg="#1e2430")

        # Floating overlay: stay on top of other apps (togglable).
        self.topmost_var = tk.BooleanVar(value=True)
        root.attributes("-topmost", True)
        self._compact = False

        self._build_widgets()
        self._poll_ui()

    # ---------------- UI layout ----------------
    def _build_widgets(self):
        tk, ttk = self.tk, self.ttk
        pad = {"padx": 12, "pady": 6}

        header = tk.Label(self.root, text="AI Voice Agent", bg="#1e2430",
                          fg="#ffffff", font=("Segoe UI", 20, "bold"))
        header.pack(pady=(16, 4))

        sub = tk.Label(self.root,
                       text="Press START — the agent introduces itself and talks to the person.",
                       bg="#1e2430", fg="#9fb3c8", font=("Segoe UI", 11))
        sub.pack(**pad)

        # ---- settings row ----
        settings = tk.Frame(self.root, bg="#262e3d")
        settings.pack(fill="x", **pad)

        tk.Label(settings, text="Agent name:", bg="#262e3d", fg="#e6edf3",
                 font=("Segoe UI", 11)).grid(row=0, column=0, sticky="w", padx=8, pady=6)
        self.name_var = tk.StringVar(value=self.cfg["agent"]["identity"]["name"])
        tk.Entry(settings, textvariable=self.name_var, width=18,
                 bg="#0f1420", fg="#ffffff", relief="flat",
                 insertbackground="#ffffff").grid(row=0, column=1, sticky="w", padx=8)

        tk.Label(settings, text="Audio source:", bg="#262e3d", fg="#e6edf3",
                 font=("Segoe UI", 11)).grid(row=0, column=2, sticky="e", padx=(24, 8))
        # The dropdown defaults to whichever capture the config asks for
        # ("device" -> Microphone, otherwise "Any app (system)"), unless the
        # user forced it via --mic / --any.
        _default_src = "Any app (system)"
        if self._source:
            _default_src = self._source
        elif self.cfg["audio"]["input"].get("capture") == "device":
            _default_src = "Microphone"
        self.source_var = tk.StringVar(value=_default_src)
        cb = ttk.Combobox(settings, textvariable=self.source_var,
                          values=["Any app (system)", "Microphone"],
                          state="readonly", width=16)
        cb.grid(row=0, column=3, sticky="w", padx=8)

        # ---- buttons ----
        btns = tk.Frame(self.root, bg="#1e2430")
        btns.pack(pady=12)
        self.start_btn = tk.Button(btns, text="▶  START", command=self.on_start,
                                   bg="#2ea043", fg="white", activebackground="#3fb950",
                                   font=("Segoe UI", 13, "bold"), relief="flat",
                                   padx=24, pady=10, cursor="hand2", width=14)
        self.start_btn.pack(side="left", padx=10)
        self.stop_btn = tk.Button(btns, text="■  STOP", command=self.on_stop,
                                  bg="#d1242f", fg="white", activebackground="#e5534b",
                                  font=("Segoe UI", 13, "bold"), relief="flat",
                                  padx=24, pady=10, cursor="hand2", width=14,
                                  state="disabled")
        self.stop_btn.pack(side="left", padx=10)

        # ---- overlay options (floating window) ----
        ov = tk.Frame(self.root, bg="#1e2430")
        ov.pack(pady=(0, 4))
        tk.Checkbutton(ov, text="📌 Always on top (floating)", variable=self.topmost_var,
                       command=self._toggle_topmost, bg="#1e2430", fg="#9fb3c8",
                       selectcolor="#1e2430", activebackground="#1e2430",
                       activeforeground="#e6edf3", highlightthickness=0,
                       font=("Segoe UI", 10)).pack(side="left", padx=(0, 12))
        tk.Button(ov, text="▭ Compact", command=self._toggle_compact,
                  bg="#262e3d", fg="#e6edf3", activebackground="#3d4556",
                  activeforeground="#ffffff", relief="flat", cursor="hand2",
                  font=("Segoe UI", 10)).pack(side="left", padx=4)
        tk.Button(ov, text="⤢ Full", command=self._toggle_full,
                  bg="#262e3d", fg="#e6edf3", activebackground="#3d4556",
                  activeforeground="#ffffff", relief="flat", cursor="hand2",
                  font=("Segoe UI", 10)).pack(side="left", padx=4)

        # ---- status ----
        self.status_var = tk.StringVar(value="● Ready — choose audio source, then press START")
        tk.Label(self.root, textvariable=self.status_var, bg="#1e2430",
                 fg="#58a6ff", font=("Segoe UI", 11, "bold")).pack(pady=(4, 2))

        # ---- audio input meter (shows whether the agent is HEARING anything) --
        meter = tk.Frame(self.root, bg="#1e2430")
        meter.pack(fill="x", padx=12, pady=(0, 2))
        tk.Label(meter, text="🎧 Hearing:", bg="#1e2430", fg="#9fb3c8",
                 font=("Segoe UI", 10)).pack(side="left")
        self.meter_bar = tk.Frame(meter, width=260, height=12, bg="#0f1420",
                                  highlightthickness=1, highlightbackground="#333")
        self.meter_bar.pack(side="left", padx=8)
        self.meter_fill = tk.Frame(self.meter_bar, width=0, height=12, bg="#2ea043")
        self.meter_fill.pack(side="left")
        self.meter_var = tk.StringVar(value="0% (speak to test)")
        tk.Label(meter, textvariable=self.meter_var, bg="#1e2430", fg="#58a6ff",
                 font=("Consolas", 9)).pack(side="left")

        # ---- lead panel ----
        lead_frame = tk.Frame(self.root, bg="#262e3d", relief="flat")
        lead_frame.pack(fill="x", **pad)
        self.lead_name = tk.StringVar(value="Name: —")
        self.lead_contact = tk.StringVar(value="Contact: —")
        self.lead_interest = tk.StringVar(value="Interest: —")
        self.lead_status = tk.StringVar(value="Goal: capture a lead (name, contact, interest)")
        for col, var in [("Name", self.lead_name), ("Contact", self.lead_contact),
                         ("Interest", self.lead_interest)]:
            tk.Label(lead_frame, text=col, bg="#262e3d", fg="#9fb3c8",
                     font=("Segoe UI", 10)).grid(row=0, column=lead_frame.grid_size()[0],
                                                 sticky="w", padx=(10, 2), pady=(8, 0))
            tk.Label(lead_frame, textvariable=var, bg="#262e3d", fg="#e6edf3",
                     font=("Segoe UI", 11, "bold")).grid(row=1,
                                                         column=lead_frame.grid_size()[0] - 1,
                                                         sticky="w", padx=(10, 14), pady=(0, 8))
        self.lead_status_lbl = tk.Label(lead_frame, textvariable=self.lead_status,
                                        bg="#262e3d", fg="#58a6ff",
                                        font=("Segoe UI", 10, "bold"))
        self.lead_status_lbl.grid(row=0, column=3, rowspan=2, sticky="e",
                                  padx=12, pady=8)

        # ---- transcript ----
        tk.Label(self.root, text="Live conversation:", bg="#1e2430", fg="#e6edf3",
                 font=("Segoe UI", 11)).pack(anchor="w", **pad)
        self.transcript = tk.Text(self.root, height=11, bg="#0f1420", fg="#e6edf3",
                                  relief="flat", font=("Consolas", 11), wrap="word")
        self.transcript.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        self.transcript.configure(state="disabled")

        self._log("Ready. You can also edit the task at tasks/my_business/.")

    # ---------------- UI thread-safe helpers ----------------
    def _ui(self, fn, *args):
        self._ui_q.put((fn, args))

    def _poll_ui(self):
        try:
            while True:
                fn, args = self._ui_q.get_nowait()
                fn(*args)
        except queue.Empty:
            pass
        self.root.after(80, self._poll_ui)

    def _log(self, line: str):
        self.transcript.configure(state="normal")
        self.transcript.insert("end", line + "\n")
        self.transcript.see("end")
        self.transcript.configure(state="disabled")

    def _toggle_topmost(self):
        self.root.attributes("-topmost", self.topmost_var.get())

    def _toggle_compact(self):
        """Shrink into a small always-on-top floating overlay (live transcript)."""
        if self._compact:
            return
        self._compact = True
        self.root.attributes("-topmost", True)
        self.topmost_var.set(True)
        self.root.geometry("400x240")
        self.transcript.configure(height=4)
        self.root.attributes("-topmost", True)

    def _toggle_full(self):
        self._compact = False
        self.root.geometry("720x560")
        self.transcript.configure(height=11)

    def _set_status(self, text: str, color: str = "#58a6ff"):
        self.status_var.set(text)
        self.root.children  # noop to keep ref

    def _set_level(self, pct: int, speaking: bool):
        """Update the audio-input meter from the capture feed."""
        try:
            w = max(0, min(260, int(260 * pct / 100)))
            self.meter_fill.configure(width=w,
                                      bg="#3fb950" if speaking else "#2ea043")
            self.meter_var.set(f"{pct}% {'(SPEECH)' if speaking else ''}")
        except Exception:
            pass

    def _refresh_lead(self):
        """Push the current lead state to the lead panel."""
        ctrl = self.ctrl
        if not ctrl:
            return
        lead = ctrl.lead
        self.lead_name.set(f"Name: {lead.name or '—'}")
        self.lead_contact.set(f"Contact: {lead.phone or lead.email or '—'}")
        self.lead_interest.set(f"Interest: {lead.interest or '—'}")
        if lead.captured:
            self.lead_status.set("🎯 LEAD CAPTURED ✓")
            self.lead_status_lbl.configure(fg="#3fb950")
        elif lead.missing():
            self.lead_status.set(f"Still need: {', '.join(lead.missing())}")
            self.lead_status_lbl.configure(fg="#e3b341")
        else:
            self.lead_status.set("Collecting lead info…")
            self.lead_status_lbl.configure(fg="#58a6ff")

    def _show_lead_changes(self, changes):
        for c in changes:
            if c not in self._lead_shown:
                self._lead_shown.add(c)
                self._log(c)

    # ---------------- actions ----------------
    def on_start(self):
        if self.running:
            return
        self.running = True
        self.start_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")
        name = self.name_var.get().strip() or "Naveed"
        source = self.source_var.get()
        self._log(f"[START] Agent '{name}' | source: {source}")
        self.worker = threading.Thread(target=self._run_agent, args=(name, source),
                                       daemon=True)
        self.worker.start()

    def on_stop(self):
        self._log("[STOP] ending...")
        self._ui(self._set_status, "■ Stopped", "#e5534b")
        if self.bridge:
            self.bridge.close()
        if self.ctrl:
            self.ctrl.end_call()
        self.running = False
        self.start_btn.configure(state="normal")
        self.stop_btn.configure(state="disabled")

    # ---------------- worker: runs the agent in a background thread ----
    def _run_agent(self, name: str, source: str):
        try:
            ctrl = build_active_controller(self.cfg, self.mock)
            self.ctrl = ctrl
            opening = ctrl.start_call()

            # Build the loopback config for the chosen source
            if source.startswith("Any"):
                capture = "system_loopback"      # hear the person from system out
                output_device = self.cfg["audio"]["output"].get("device")
                output_sr = self.cfg["audio"]["output"].get("sample_rate", 24000)
            else:  # Microphone
                capture = "device"               # hear from the microphone
                output_device = self.cfg["audio"]["output"].get("device")  # speaker
                output_sr = self.cfg["audio"]["output"].get("sample_rate", 24000)

            loop_cfg = LoopbackConfig(
                capture_mode=capture,
                input_device=self.cfg["audio"]["input"].get("device"),
                output_device=output_device,
                sample_rate=self.cfg["audio"]["input"].get("sample_rate", 16000),
                output_sample_rate=output_sr,
                energy_threshold=self.cfg["audio"]["vad"].get("energy_threshold", 0.02),
                min_silence_ms=self.cfg["audio"]["vad"].get("min_silence_ms", 800),
                barge_in=self.cfg["audio"]["barge_in"].get("enabled", True),
                barge_sensitivity=self.cfg["audio"]["barge_in"].get("sensitivity", 0.55),
            )

            def say(text: str):
                self._ui(self._log, f"Agent: {text}")
                audio = ctrl.speak(text)
                try:
                    samples, sr = decode_audio_to_float32(audio)
                    self.bridge.play_samples(samples, sr)
                except Exception as e:  # pragma: no cover
                    log.warning("playback failed: %s", e)

            bridge = LoopbackBridge(lambda seg: None, cfg=loop_cfg)
            self.bridge = bridge
            bridge.open()
            self._ui(self._set_status, f"● Speaking to person ({source}) ...")

            # Live audio-level meter: report RMS of what we're hearing so you can
            # SEE whether the person's voice is actually reaching the agent.
            import numpy as _np
            def _level(samples):
                rms = float(_np.sqrt(_np.mean(samples.astype(_np.float32) ** 2)))
                pct = int(min(100, max(0, rms * 2000)))
                self._ui(self._set_level, pct, pct > 2)
            bridge.on_level = _level

            # 1) introduce yourself, 2) task opening, 3) conversation loop
            greeting = self.cfg["agent"]["identity"].get("greeting", "Hi, I'm {name}.")
            say(greeting.format(name=name))
            if opening:
                say(opening)

            def on_utterance(segment):
                try:
                    from main import _float32_to_wav
                    rate = getattr(bridge, "capture_rate", loop_cfg.sample_rate)
                    wav = _float32_to_wav(segment, rate)
                    person, reply, audio, changes = process_audio_turn(ctrl, wav, loop_cfg.sample_rate)
                    if not person:
                        return
                    self._ui(self._log, f"Person: {person}")
                    if changes:
                        self._ui(self._show_lead_changes, changes)
                    if reply:
                        self._ui(self._log, f"Agent: {reply}")
                    self._ui(self._refresh_lead)
                    if audio:
                        samples, sr = decode_audio_to_float32(audio)
                        bridge.play_samples(samples, sr)
                except Exception as e:  # pragma: no cover
                    log.exception("turn error: %s", e)

            bridge.on_utterance = on_utterance

            # keep running until stopped
            while self.running:
                import time
                time.sleep(0.5)
            bridge.close()
            ctrl.end_call()
        except Exception as e:  # pragma: no cover
            log.exception("agent error")
            self._ui(self._log, f"[ERROR] {e}")
            self._ui(self._set_status, "× Error — see console", "#e5534b")
            self._ui(self._reset_buttons)

    def _reset_buttons(self):
        self.running = False
        self.start_btn.configure(state="normal")
        self.stop_btn.configure(state="disabled")


def main():
    ap = argparse.ArgumentParser(description="AI Voice Agent GUI")
    ap.add_argument("--mock", action="store_true",
                    help="force all providers to mock (fully offline)")
    ap.add_argument("--config", default=None, help="path to config.yaml")
    src_grp = ap.add_mutually_exclusive_group()
    src_grp.add_argument("--mic", action="store_true",
                         help="hear the person via the microphone (default when "
                              "audio.input.capture=device)")
    src_grp.add_argument("--any", action="store_true",
                         help="hear whatever plays on the PC (loopback / Stereo Mix)")
    args = ap.parse_args()

    source = None
    if args.mic:
        source = "Microphone"
    elif args.any:
        source = "Any app (system)"

    cfg = load_config(args.config)

    # Diagnostic: show Python version + audio devices up front so we can confirm
    # the agent is running on the right interpreter and can see the loopback.
    import sys as _sys
    log.info("Python: %s.%s.%s (%s)",
             _sys.version_info[0], _sys.version_info[1], _sys.version_info[2], _sys.executable)
    try:
        from phone.loopback import list_devices
        for row in list_devices():
            log.info("AUDIO  %s", row)
    except Exception as e:
        log.warning("Could not list audio devices: %s", e)

    import tkinter as tk
    root = tk.Tk()
    VoiceAgentGUI(root, cfg, mock=args.mock, source=source)
    root.mainloop()


if __name__ == "__main__":
    main()
