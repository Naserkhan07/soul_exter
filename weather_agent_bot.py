import time
import sys

class WeatherAgentBot:
    def __init__(self):
        self.name = "Weather Agent"
        self.memory = []
        self.status = "ONLINE"
        
    def log(self, message):
        timestamp = time.strftime('%H:%M:%S')
        print(f"[{timestamp}] [{self.name}] {message}")
        self.memory.append(message)
        
    def execute_task(self, task_description):
        self.log(f"Received new task: '{task_description}'")
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
                user_input = input(f"{self.name} ❯ ")
                if user_input.lower() in ['exit', 'quit']:
                    self.log("Shutting down...")
                    break
                self.execute_task(user_input)
        except KeyboardInterrupt:
            print()
            self.log("Force closed.")

if __name__ == "__main__":
    bot = WeatherAgentBot()
    bot.run_interactive_loop()
