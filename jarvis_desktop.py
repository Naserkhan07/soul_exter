import tkinter as tk
from tkinter import scrolledtext
import threading
import time
import sys
import os

# Import our Jarvis modules
from modules.brain import process_prompt
from modules.observer import JarvisObserver

class JarvisDesktopApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Jarvis Core")
        self.root.geometry("400x550+100+100") # Width x Height + X + Y
        self.root.configure(bg="#040814")
        
        # Make it a borderless, floating window
        self.root.overrideredirect(True)
        # Keep it always on top of other windows
        self.root.attributes('-topmost', True)
        
        # Variables for dragging the borderless window
        self.drag_x = 0
        self.drag_y = 0

        self.setup_ui()
        self.start_observer()

    def setup_ui(self):
        # Custom Title Bar (Draggable)
        self.title_bar = tk.Frame(self.root, bg="#0f172a", relief="flat", bd=0)
        self.title_bar.pack(fill=tk.X)
        self.title_bar.bind("<ButtonPress-1>", self.start_drag)
        self.title_bar.bind("<B1-Motion>", self.do_drag)

        self.title_label = tk.Label(self.title_bar, text="🤖 JARVIS // ACTIVE", bg="#0f172a", fg="#60a5fa", font=("Courier", 10, "bold"))
        self.title_label.pack(side=tk.LEFT, padx=10, pady=5)
        self.title_label.bind("<ButtonPress-1>", self.start_drag)
        self.title_label.bind("<B1-Motion>", self.do_drag)

        # Close Button
        self.close_btn = tk.Button(self.title_bar, text="✖", bg="#0f172a", fg="#ef4444", bd=0, font=("Courier", 10, "bold"), command=self.root.destroy)
        self.close_btn.pack(side=tk.RIGHT, padx=10)

        # Output Terminal (Scrollable)
        self.output_area = scrolledtext.ScrolledText(self.root, bg="#040814", fg="#94a3b8", font=("Courier", 9), bd=0, wrap=tk.WORD)
        self.output_area.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        self.output_area.insert(tk.END, "[SYSTEM] Jarvis Desktop initialized.\n[SYSTEM] Floating mode engaged.\n\n")
        self.output_area.configure(state=tk.DISABLED)

        # Optics Feed (Mini label at bottom)
        self.optics_label = tk.Label(self.root, text="👁️ Optics: Scanning...", bg="#040814", fg="#34d399", font=("Courier", 8), anchor="w")
        self.optics_label.pack(fill=tk.X, padx=10, pady=2)

        # Input Frame
        self.input_frame = tk.Frame(self.root, bg="#040814")
        self.input_frame.pack(fill=tk.X, padx=10, pady=10)

        self.prompt_prefix = tk.Label(self.input_frame, text="❯", bg="#040814", fg="#facc15", font=("Courier", 12, "bold"))
        self.prompt_prefix.pack(side=tk.LEFT)

        self.input_field = tk.Entry(self.input_frame, bg="#040814", fg="#60a5fa", font=("Courier", 10), bd=0, insertbackground="#60a5fa")
        self.input_field.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        self.input_field.bind("<Return>", self.handle_input)
        self.input_field.focus()

    def start_drag(self, event):
        self.drag_x = event.x
        self.drag_y = event.y

    def do_drag(self, event):
        x = self.root.winfo_pointerx() - self.drag_x
        y = self.root.winfo_pointery() - self.drag_y
        self.root.geometry(f"+{x}+{y}")

    def append_text(self, text, color="#94a3b8"):
        self.output_area.configure(state=tk.NORMAL)
        self.output_area.insert(tk.END, text + "\n")
        self.output_area.see(tk.END)
        self.output_area.configure(state=tk.DISABLED)

    def handle_input(self, event):
        command = self.input_field.get().strip()
        if not command:
            return
            
        self.input_field.delete(0, tk.END)
        self.append_text(f"❯ {command}", color="#facc15")
        
        # Process command in a separate thread so UI doesn't freeze
        threading.Thread(target=self.process_command_thread, args=(command,), daemon=True).start()

    def process_command_thread(self, command):
        logs = process_prompt(command)
        for log in logs:
            self.root.after(0, self.append_text, log)

    def start_observer(self):
        self.observer = JarvisObserver(workspace_dir=".")
        self.update_optics()

    def update_optics(self):
        try:
            observations = self.observer.observe()
            if observations:
                # Show the latest observation
                self.optics_label.configure(text=observations[-1])
        except Exception:
            pass
        # Loop every 2 seconds
        self.root.after(2000, self.update_optics)

if __name__ == "__main__":
    root = tk.Tk()
    app = JarvisDesktopApp(root)
    root.mainloop()
