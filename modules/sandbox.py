import os
import subprocess

def test_in_docker_sandbox(script_name="infinite_app.py"):
    """
    Creates an isolated Docker Sandbox to test generated code 
    so it doesn't harm your host laptop.
    """
    if not os.path.exists(script_name):
        return f"🛑 [SANDBOX] Cannot find {script_name} to test."

    print(f"📦 [SANDBOX] Building isolated Virtual Container for {script_name}...")

    # Write the Dockerfile
    dockerfile_content = f"""FROM python:3.9-slim
WORKDIR /app
COPY {script_name} .
CMD ["python", "{script_name}"]
"""
    with open("Dockerfile.sandbox", "w") as f:
        f.write(dockerfile_content)

    try:
        # Build the invisible Sandbox
        print("🔨 [SANDBOX] Compiling Docker Image...")
        subprocess.run(["docker", "build", "-t", "jarvis-sandbox", "-f", "Dockerfile.sandbox", "."], 
                       check=True, capture_output=True)
                       
        # Run the Sandbox
        print("▶️ [SANDBOX] Running code inside isolated container...")
        result = subprocess.run(["docker", "run", "--rm", "jarvis-sandbox"], 
                                check=True, capture_output=True, text=True)
                                
        return f"🛡️ [SANDBOX] Code executed safely inside isolation.\nContainer Output:\n{result.stdout.strip()}"
        
    except FileNotFoundError:
        # Docker is not installed on the laptop
        return f"""🛑 [SANDBOX] Docker is not installed on your machine!
💡 I have written 'Dockerfile.sandbox' for you.
Please install Docker Desktop to unlock full isolation mode."""
    except subprocess.CalledProcessError as e:
        return f"⚠️ [SANDBOX] Code crashed inside isolation. Your laptop is safe.\nError: {e.stderr}"

if __name__ == "__main__":
    print(test_in_docker_sandbox())
