import speech_recognition as sr

def listen_for_command():
    recognizer = sr.Recognizer()
    
    with sr.Microphone() as source:
        print("\n🎤 Jarvis is adjusting to ambient noise... Please wait.")
        recognizer.adjust_for_ambient_noise(source, duration=1)
        print("🟢 Jarvis is listening! Speak now...")
        
        try:
            # Listen with a timeout so it doesn't hang forever
            audio = recognizer.listen(source, timeout=5, phrase_time_limit=10)
            print("🔄 Processing audio...")
            
            # Using Google's free Web Speech API (does not require an API key)
            command = recognizer.recognize_google(audio)
            print(f"🗣️ You said: '{command}'")
            return command.lower()
            
        except sr.WaitTimeoutError:
            print("⏳ No speech detected.")
            return None
        except sr.UnknownValueError:
            print("🤷 Jarvis could not understand the audio.")
            return None
        except sr.RequestError as e:
            print(f"🛑 Could not request results from Speech Recognition service; {e}")
            return None
