import time
from runner.executor import run_command
from analyzer.error_parser import parse_python_error
from healer.rule_engine import apply_fix

def start_autonomous_loop(script_name="infinite_app.py"):
    """
    The Auto-GPT Loop: Jarvis runs the code, catches crashes,
    heals itself, and loops infinitely until the script works perfectly.
    """
    print(f"♾️ [AUTO-LOOP] Engaging continuous execution and healing on {script_name}...")
    
    max_iterations = 5
    iteration = 1
    
    while iteration <= max_iterations:
        print(f"\n🔄 [AUTO-LOOP] Iteration {iteration}: Running {script_name}...")
        result = run_command(["python", script_name])
        
        if result['exit_code'] == 0:
            return f"✅ [AUTO-LOOP] Success! The script ran perfectly on iteration {iteration}.\nOutput:\n{result['stdout'].strip()}"
            
        print(f"⚠️ [AUTO-LOOP] Crash detected! Engaging Healer...")
        parsed_error = parse_python_error(result['stderr'])
        
        if parsed_error:
            fixed = apply_fix(parsed_error)
            if fixed:
                print("🔧 [AUTO-LOOP] Code healed. Restarting loop...")
                iteration += 1
                time.sleep(1)
                continue
            else:
                return f"🛑 [AUTO-LOOP] Failed to heal the error: {parsed_error['type']}."
        else:
            return f"🛑 [AUTO-LOOP] Unrecognized crash output."
            
    return "🛑 [AUTO-LOOP] Max iterations reached. The code is still broken."

if __name__ == "__main__":
    print(start_autonomous_loop("broken.py"))
