"""Audio layer — microphone, speaker, VAD and streaming.

On Windows these modules need PyAudio/SoundDevice. The agent also runs fully
in "text mode" with mock models, which needs none of this.

StreamingVoiceEngine wires:
  mic → VAD → (silence detected) → callback(text) → tts.synthesize → speaker
with a barge-in thread that can stop playback when the mic hears speech.
"""
