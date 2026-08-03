import subprocess

def commit_fix(file_path, error_type):
    """
    Jarvis uses this to save its work to Version Control (Git) 
    so it remembers how it fixed the code.
    """
    try:
        # 1. Add the file to git
        subprocess.run(['git', 'add', file_path], check=True, capture_output=True)
        
        # 2. Write an automated commit message
        commit_msg = f"🔧 JARVIS Auto-Fix: Resolved {error_type} in {file_path}"
        
        # 3. Commit the code
        subprocess.run(['git', 'commit', '-m', commit_msg], check=True, capture_output=True)
        
        print(f"📦 [GIT] JARVIS saved its fix to version history: '{commit_msg}'")
        return True
    except subprocess.CalledProcessError as e:
        # Happens if there's nothing to commit, or git isn't configured, we just ignore gracefully
        return False
    except Exception as e:
        print(f"📦 [GIT] Could not commit: {e}")
        return False
