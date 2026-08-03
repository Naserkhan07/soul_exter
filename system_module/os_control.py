import os
import platform
import subprocess

# Import our new modules!
from modules.web_builder import scaffold_3d_website
from modules.email_agent import send_automated_email

def execute_os_command(command_text):
    """
    Parses natural language commands to control the laptop natively.
    """
    os_name = platform.system().lower()
    
    # 1. 3D WEBSITE GENERATION
    if "create website" in command_text or "build a website" in command_text:
        print("🌐 Triggering Web Builder Module...")
        result = scaffold_3d_website("jarvis_generated_web")
        return f"I have built the 3D website for you, sir. {result}"
        
    # 2. EMAIL AUTOMATION
    elif "send email" in command_text:
        # In a fully NLP-integrated Jarvis, it would use an LLM to extract the name and message.
        # Here is the deterministic hook:
        print("📧 Triggering Email Agent...")
        # Hardcoded example for demonstration:
        result = send_automated_email(
            to_email="test@example.com", 
            subject="Automated Message from Jarvis", 
            body="Hello. I am Jarvis, an autonomous software engineer. My creator asked me to send this."
        )
        return result

    # 3. OPENING APPLICATIONS
    elif "open" in command_text:
        app_name = command_text.split("open ")[-1].strip()
        try:
            if "windows" in os_name:
                os.system(f"start {app_name}")
            elif "darwin" in os_name: # MacOS
                os.system(f"open -a '{app_name}'")
            else: # Linux
                os.system(f"{app_name} &")
            return f"Opening {app_name} for you, sir."
        except Exception as e:
            return f"I encountered an error trying to open {app_name}."

    # 4. FILE SYSTEM ACCESS
    elif "list files" in command_text:
        files = os.listdir('.')
        file_list = ", ".join(files[:5])
        return f"The current directory contains: {file_list}."
        
    # 5. SELF-HEALING TRIGGER
    elif "fix my code" in command_text:
        return "TRIGGER_HEALER"

    return "I heard you, but I do not have a module for that command yet."
