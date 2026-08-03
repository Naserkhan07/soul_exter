import subprocess

def run_command(command_list):
    """
    Executes a command and returns the stdout, stderr, and exit code.
    """
    result = subprocess.run(
        command_list, 
        capture_output=True, 
        text=True
    )
    return {
        "stdout": result.stdout,
        "stderr": result.stderr,
        "exit_code": result.returncode
    }
