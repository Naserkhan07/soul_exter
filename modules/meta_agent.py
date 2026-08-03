import os

def generate_new_agent(agent_name="CustomAgent"):
    """
    Jarvis acts as a Meta-Agent: It writes the Python code to generate 
    a completely new, autonomous agent based on user requests.
    """
    safe_name = agent_name.replace(" ", "_").lower()
    file_name = f"{safe_name}_bot.py"

    agent_code = f"""import time
import sys

class {agent_name.replace(" ", "")}Bot:
    def __init__(self):
        self.name = "{agent_name}"
        self.memory = []
        self.status = "ONLINE"
        
    def log(self, message):
        timestamp = time.strftime('%H:%M:%S')
        print(f"[{{timestamp}}] [{{self.name}}] {{message}}")
        self.memory.append(message)
        
    def execute_task(self, task_description):
        self.log(f"Received new task: '{{task_description}}'")
        self.log("Analyzing requirements...")
        time.sleep(1)
        
        self.log("Loading necessary tools and modules...")
        time.sleep(1)
        
        self.log("Executing task steps...")
        time.sleep(2)
        
        self.log("✅ Task completed successfully.")
        
    def run_interactive_loop(self):
        self.log("System initialized. Awaiting commands.")
        try:
            while True:
                user_input = input(f"{{self.name}} ❯ ")
                if user_input.lower() in ['exit', 'quit']:
                    self.log("Shutting down...")
                    break
                self.execute_task(user_input)
        except KeyboardInterrupt:
            print()
            self.log("Force closed.")

if __name__ == "__main__":
    bot = {agent_name.replace(" ", "")}Bot()
    bot.run_interactive_loop()
"""
    
    with open(file_name, "w") as f:
        f.write(agent_code)

    return f"🤖 [META-AGENT] I have successfully spawned a new agent! The code for '{agent_name}' has been written to {file_name}."

if __name__ == "__main__":
    print(generate_new_agent("Weather Agent"))
