import psutil
import time
import os

class JarvisObserver:
    def __init__(self, workspace_dir="."):
        self.workspace_dir = workspace_dir
        self.last_seen_process = None
        self.last_modified_file = None
        self.last_modified_time = 0

    def scan_processes(self):
        """Scans the CPU to see what application the user is actively using."""
        try:
            # Find the process using the most CPU right now (ignoring background services)
            top_process = None
            max_cpu = 0.0
            
            for proc in psutil.process_iter(['name', 'cpu_percent']):
                try:
                    name = proc.info['name']
                    cpu = proc.info['cpu_percent']
                    
                    ignore_list = ['System Idle Process', 'python', 'python3', 'bash', 'sshd']
                    if cpu is not None and cpu > max_cpu and name not in ignore_list:
                        max_cpu = cpu
                        top_process = name
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
                    
            return top_process
        except Exception:
            return None

    def scan_workspace(self):
        """Scans the project folder to see what file the user is editing."""
        try:
            latest_file = None
            latest_time = 0
            
            for root, _, files in os.walk(self.workspace_dir):
                if '.git' in root or '__pycache__' in root:
                    continue
                for file in files:
                    if file.endswith('.db') or file.endswith('.pyc'):
                        continue
                    filepath = os.path.join(root, file)
                    mtime = os.path.getmtime(filepath)
                    if mtime > latest_time:
                        latest_time = mtime
                        latest_file = file
                        
            return latest_file, latest_time
        except Exception:
            return None, 0

    def observe(self):
        """Returns a string describing what the user is doing right now."""
        logs = []
        
        # 1. Check Apps
        current_process = self.scan_processes()
        if current_process and current_process != self.last_seen_process:
            self.last_seen_process = current_process
            logs.append(f"👁️ I see you opened/focused on: {current_process}")
            
        # 2. Check Files
        recent_file, recent_time = self.scan_workspace()
        if recent_file and recent_time > self.last_modified_time:
            # Only trigger if it's actually a new modification
            if self.last_modified_time != 0: 
                logs.append(f"👁️ I see you are editing the file: {recent_file}")
            self.last_modified_time = recent_time
            
        return logs

