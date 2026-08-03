# Soul Exter - Deterministic Jarvis

A completely offline, rule-based autonomous agent framework.

## 1. Jarvis Workflow Matrix (Dashboard)
This launches a beautiful, hacker-themed web dashboard where you can assign tasks to Jarvis. It has a background thread that constantly watches the queue, executes your commands on your machine, logs the outputs live to the web page, and automatically triggers the code-healer if a script crashes!

**To run the UI Dashboard:**
```bash
./start_matrix.sh
```
Then open `http://127.0.0.1:5000` in your web browser.

## 2. Voice Module
*(Requires physical computer with microphone)*
You can control Jarvis with your voice using offline Speech-to-Text.
**To run Voice Jarvis:**
```bash
pip install -r requirements_voice.txt
python jarvis_voice.py
```

## 3. Core Capabilities
* **Runner Module:** Executes tasks safely.
* **Analyzer Module:** Parses exact error types from `stderr` outputs.
* **Healer Module:** Uses python AST parsing and difflib to mathematically correct typos and missing syntax in your code files.
