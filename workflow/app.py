import sqlite3
import threading
import time
import sys
import os

# Add parent directory to path so we can import our old modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flask import Flask, render_template, request, jsonify
from runner.executor import run_command
from analyzer.error_parser import parse_python_error
from healer.rule_engine import apply_fix

app = Flask(__name__)
DB_FILE = 'jarvis_workflow.db'

def init_db():
    with sqlite3.connect(DB_FILE) as conn:
        c = conn.cursor()
        c.execute('''
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT,
                command TEXT,
                status TEXT,
                logs TEXT
            )
        ''')
        conn.commit()

# --- ROUTES ---

@app.route('/')
def dashboard():
    return render_template('index.html')

@app.route('/api/tasks', methods=['GET'])
def get_tasks():
    with sqlite3.connect(DB_FILE) as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("SELECT * FROM tasks ORDER BY id DESC")
        tasks = [dict(row) for row in c.fetchall()]
    return jsonify(tasks)

@app.route('/api/tasks', methods=['POST'])
def add_task():
    data = request.json
    name = data.get('name', 'Unnamed Task')
    command = data.get('command', '')
    
    with sqlite3.connect(DB_FILE) as conn:
        c = conn.cursor()
        c.execute("INSERT INTO tasks (name, command, status, logs) VALUES (?, ?, 'PENDING', '')", 
                  (name, command))
        conn.commit()
    return jsonify({"status": "success"})

@app.route('/api/tasks/<int:task_id>', methods=['DELETE'])
def delete_task(task_id):
    with sqlite3.connect(DB_FILE) as conn:
        c = conn.cursor()
        c.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
        conn.commit()
    return jsonify({"status": "success"})


# --- JARVIS BACKGROUND WORKER ---

def append_log(task_id, log_msg):
    with sqlite3.connect(DB_FILE) as conn:
        c = conn.cursor()
        c.execute("SELECT logs FROM tasks WHERE id = ?", (task_id,))
        current_logs = c.fetchone()[0]
        new_logs = current_logs + "\n" + log_msg if current_logs else log_msg
        c.execute("UPDATE tasks SET logs = ? WHERE id = ?", (new_logs, task_id))
        conn.commit()

def set_status(task_id, status):
    with sqlite3.connect(DB_FILE) as conn:
        c = conn.cursor()
        c.execute("UPDATE tasks SET status = ? WHERE id = ?", (status, task_id))
        conn.commit()

def jarvis_background_worker():
    print("🤖 Jarvis Background Worker Started.")
    while True:
        try:
            with sqlite3.connect(DB_FILE) as conn:
                conn.row_factory = sqlite3.Row
                c = conn.cursor()
                c.execute("SELECT * FROM tasks WHERE status = 'PENDING' LIMIT 1")
                task = c.fetchone()
                
            if task:
                task_id = task['id']
                command = task['command']
                
                set_status(task_id, 'RUNNING')
                append_log(task_id, f"▶️ Jarvis started executing: {command}")
                
                command_list = command.split()
                
                max_retries = 3
                attempt = 1
                success = False
                
                while attempt <= max_retries:
                    append_log(task_id, f"\n--- Attempt {attempt} ---")
                    result = run_command(command_list)
                    
                    if result['stdout']:
                        append_log(task_id, result['stdout'].strip())
                        
                    if result['exit_code'] == 0:
                        append_log(task_id, "✅ Execution Successful.")
                        success = True
                        break
                        
                    append_log(task_id, f"⚠️ Error detected (Exit Code {result['exit_code']})")
                    append_log(task_id, result['stderr'].strip())
                    
                    # Self-Healing Logic
                    if command_list[0] in ['python', 'python3']:
                        set_status(task_id, 'HEALING')
                        parsed_error = parse_python_error(result['stderr'])
                        
                        if parsed_error:
                            append_log(task_id, f"🔍 Jarvis Analyzed Error: {parsed_error['type']}")
                            fixed = apply_fix(parsed_error)
                            
                            if fixed:
                                append_log(task_id, "🔧 Jarvis Applied Fix. Retrying...")
                                attempt += 1
                                set_status(task_id, 'RUNNING')
                                time.sleep(1)
                                continue
                            else:
                                append_log(task_id, "🛑 Jarvis has no deterministic rule for this error yet.")
                                break
                        else:
                            append_log(task_id, "🛑 Jarvis could not parse the error structure.")
                            break
                    else:
                        append_log(task_id, "🛑 Jarvis only auto-heals python tasks currently.")
                        break
                        
                if success:
                    set_status(task_id, 'COMPLETED')
                else:
                    set_status(task_id, 'FAILED')
                    
        except Exception as e:
            print(f"Worker Error: {e}")
            
        time.sleep(2) # Poll every 2 seconds

if __name__ == '__main__':
    init_db()
    # Start the background worker thread
    threading.Thread(target=jarvis_background_worker, daemon=True).start()
    # Run the web server
    app.run(port=5000, debug=False)
