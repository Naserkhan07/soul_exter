from gtts import gTTS
import os

def speak(text):
    tts = gTTS(text=text, lang='en')
    tts.save('jarvis_response.mp3')
    os.system('mpg123 jarvis_response.mp3')
