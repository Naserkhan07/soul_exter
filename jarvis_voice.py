import sys
from voice_module.speak import init_engine, speak
from voice_module.listen import listen_for_command
from system_module.os_control import execute_os_command
import subprocess

def run_voice_jarvis():
    tts_engine = init_engine()
    speak("Jarvis systems online. Awaiting your command.", tts_engine)
    
    while True:
        command = listen_for_command()
        
        if not command:
            continue
            
        if "exit" in command or "stop listening" in command or "goodbye" in command:
            speak("Powering down. Goodbye, sir.", tts_engine)
            break
            
        # Route command to OS controller
        response = execute_os_command(command)
        
        # Check if the command was to run our self-healing script from earlier
        if response == "TRIGGER_HEALER":
            speak("Initiating self-healing protocol on broken dot p y.", tts_engine)
            # Run the jarvis.py we made earlier!
            subprocess.run(["python", "jarvis.py", "python", "broken.py"])
            speak("Self-healing complete.", tts_engine)
        else:
            # Speak the OS response
            speak(response, tts_engine)

if __name__ == "__main__":
    try:
        run_voice_jarvis()
    except KeyboardInterrupt:
        print("\nForce quitting Jarvis...")
        sys.exit(0)
