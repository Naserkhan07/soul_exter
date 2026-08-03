import os
import re

def scan_local_code_for_secrets(directory="."):
    """
    Jarvis acts as a Cybersecurity Defender (SAST Tool).
    It scans your local code files to ensure you didn't accidentally 
    hardcode passwords, API keys, or secrets into your public repository.
    """
    alerts = []
    
    # Simple regex to look for hardcoded secrets
    secret_pattern = re.compile(r'(api_key|password|secret|token)\s*=\s*[\'"][^\'"]+[\'"]', re.IGNORECASE)
    
    for root, _, files in os.walk(directory):
        if '.git' in root or '__pycache__' in root or 'node_modules' in root:
            continue
            
        for file in files:
            if not file.endswith('.py') and not file.endswith('.js') and not file.endswith('.txt'):
                continue
                
            filepath = os.path.join(root, file)
            try:
                with open(filepath, 'r') as f:
                    for line_num, line in enumerate(f.readlines(), 1):
                        if secret_pattern.search(line):
                            alerts.append(f"   ⚠️ WARNING in {file} (Line {line_num}): Hardcoded secret detected!")
            except Exception:
                pass
                
    if alerts:
        result = "🛡️ [SECURITY DEFENDER] Scan complete! I found potential security vulnerabilities in your code:\n" + "\n".join(alerts)
    else:
        result = "🛡️ [SECURITY DEFENDER] Scan complete! Your code looks clean. No hardcoded passwords detected."
        
    return result

if __name__ == "__main__":
    print(scan_local_code_for_secrets())
