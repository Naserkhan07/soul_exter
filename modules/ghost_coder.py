import os
import time
import threading

def start_ghost_coder(file_to_watch="main.py"):
    """
    Watches a specific file. If it detects a save, it can automatically 
    run the code, check for errors, or apply formatting.
    """
    def watch_file():
        if not os.path.exists(file_to_watch):
            with open(file_to_watch, "w") as f:
                f.write("# Ghost coder is watching this file...\n")
                
        last_mtime = os.path.getmtime(file_to_watch)
        print(f"👻 [GHOST CODER] Actively monitoring {file_to_watch} for changes...")
        
        # In a full version, this runs infinitely. We'll simulate a brief watch session here.
        for _ in range(5):
            time.sleep(2)
            try:
                current_mtime = os.path.getmtime(file_to_watch)
                if current_mtime > last_mtime:
                    print(f"👻 [GHOST CODER] Detected save in {file_to_watch}. Auto-formatting...")
                    # Basic auto-format example: removing trailing whitespace
                    with open(file_to_watch, 'r') as f:
                        lines = [line.rstrip() + '\n' for line in f.readlines()]
                    with open(file_to_watch, 'w') as f:
                        f.writelines(lines)
                    last_mtime = os.path.getmtime(file_to_watch)
            except Exception:
                pass
                
    threading.Thread(target=watch_file, daemon=True).start()
    return f"👻 Ghost Coder activated! It is now monitoring {file_to_watch} in the background."

if __name__ == "__main__":
    print(start_ghost_coder())
