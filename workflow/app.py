import sqlite3
import threading
import time
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flask import Flask, render_template, request, jsonify
from runner.executor import run_command
from analyzer.error_parser import parse_python_error
from healer.rule_engine import apply_fix
from modules.brain import process_prompt
from modules.observer import JarvisObserver

app = Flask(__name__)
DB_FILE = 'jarvis_workflow.db'

# Global memory for the observer
observer_logs = ["[SYSTEM] Jarvis Optics Online. Scanning environment..."]

def init_db():
    with sqlite3.connect(DB_FILE) as conn:
        c = conn.cursor()
        c.execute('''
            CREATE TABLE IF NOT EXISTS prompts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                prompt TEXT,
                response TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        conn.commit()

def background_observer():
    """Background thread that constantly watches what the user is doing."""
    print("👁️ Jarvis Observer Thread Started.")
    observer = JarvisObserver(workspace_dir="/home/user/soul_exter")
    
    while True:
        try:
            new_observations = observer.observe()
            for obs in new_observations:
                observer_logs.append(f"[{time.strftime('%H:%M:%S')}] {obs}")
                # Keep logs array trimmed to last 50 events
                if len(observer_logs) > 50:
                    observer_logs.pop(0)
        except Exception as e:
            pass
        time.sleep(3) # Check every 3 seconds (very low CPU usage)

@app.route('/')
def dashboard():
    return render_template('index.html')

@app.route('/api/prompt', methods=['POST'])
def handle_prompt():
    data = request.json
    prompt_text = data.get('prompt', '')
    
    # Process the prompt through Jarvis's brain
    logs = process_prompt(prompt_text)
    response_text = "\n".join(logs)
    
    # Save to history
    with sqlite3.connect(DB_FILE) as conn:
        c = conn.cursor()
        c.execute("INSERT INTO prompts (prompt, response) VALUES (?, ?)", (prompt_text, response_text))
        conn.commit()
        
    return jsonify({"status": "success", "logs": logs})

@app.route('/api/optics', methods=['GET'])
def get_optics():
    """Endpoint for the frontend to fetch what Jarvis is seeing right now."""
    return jsonify({"logs": observer_logs[-10:]}) # Return last 10 observations

if __name__ == '__main__':
    init_db()
    # Start the continuous observation thread
    threading.Thread(target=background_observer, daemon=True).start()
    app.run(port=5000, debug=False)
