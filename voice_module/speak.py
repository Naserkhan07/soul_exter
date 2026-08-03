import pyttsx3

def init_engine():
    try:
        engine = pyttsx3.init()
        # Set speech rate
        engine.setProperty('rate', 175)
        # Set volume
        engine.setProperty('volume', 1.0)
        return engine
    except Exception as e:
        print(f"TTS Error: {e}")
        return None

def speak(text, engine=None):
    print(f"🤖 Jarvis says: {text}")
    if engine:
        try:
            engine.say(text)
            engine.runAndWait()
        except Exception as e:
            print(f"(Audio failed, text only): {text}")
