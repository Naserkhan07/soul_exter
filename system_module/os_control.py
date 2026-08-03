import os
import platform
import subprocess

def execute_os_command(command_text):
    """
    Parses natural language commands to control the laptop natively.
    """
    os_name = platform.system().lower()
    
    # 1. OPENING APPLICATIONS
    if "open" in command_text:
        # Extract everything after "open "
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

    # 2. FILE SYSTEM ACCESS (Listing files)
    elif "list files" in command_text or "what is in this folder" in command_text:
        files = os.listdir('.')
        file_list = ", ".join(files[:5]) # Only say the first 5 so Jarvis doesn't talk forever
        return f"The current directory contains: {file_list} and possibly others."
        
    # 3. SELF-HEALING INTEGRATION (Triggering the code we built earlier!)
    elif "fix my code" in command_text:
        return "TRIGGER_HEALER"

    # 4. SYSTEM CONTROLS
    elif "shutdown my laptop" in command_text:
        return "I am programmed to refuse shutting down your computer without manual confirmation, sir!"
        
    # UNKNOWN COMMAND
    return "I heard you, but I do not have a deterministic rule to execute that command yet."
