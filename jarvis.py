import sys
import time
from runner.executor import run_command
from analyzer.error_parser import parse_python_error
from healer.rule_engine import apply_fix
from modules.git_agent import commit_fix
from modules.researcher import search_stack_overflow

def main():
    if len(sys.argv) < 2:
        print("Usage: python jarvis.py <command>")
        print("Example: python jarvis.py python broken.py")
        sys.exit(1)
        
    command_list = sys.argv[1:]
    max_retries = 3
    attempt = 1
    
    while attempt <= max_retries:
        print(f"\n▶️ Running: {' '.join(command_list)} (Attempt {attempt})")
        result = run_command(command_list)
        
        if result['stdout']:
            print(result['stdout'].strip())
            
        if result['exit_code'] == 0:
            print("\n✅ Command executed successfully!")
            break
            
        print(f"\n⚠️ Error detected (Exit Code {result['exit_code']})")
        print("--- stderr ---")
        print(result['stderr'].strip())
        print("--------------")
        
        if command_list[0] == 'python' or command_list[0] == 'python3':
            parsed_error = parse_python_error(result['stderr'])
            if parsed_error:
                print(f"🔍 Analyzed Error: {parsed_error['type']} in {parsed_error['file']} at line {parsed_error['line']}")
                
                # Attempt to fix the code using our deterministic rules
                fixed = apply_fix(parsed_error)
                if fixed:
                    # ✅ NEW ABILITY: Commit to Git!
                    commit_fix(parsed_error['file'], parsed_error['type'])
                    
                    print("🔄 Retrying with fixed code...")
                    attempt += 1
                    time.sleep(1)
                    continue
                else:
                    # ✅ NEW ABILITY: Research the Web!
                    print(f"🛑 JARVIS doesn't have a hard-coded rule to fix '{parsed_error['type']}' yet.")
                    research_results = search_stack_overflow(parsed_error['type'], parsed_error['message'])
                    print(f"\n{research_results}\n")
                    break
            else:
                print("🛑 JARVIS could not parse the error output.")
                break
        else:
            print("🛑 JARVIS only supports fixing 'python' commands at the moment.")
            break

if __name__ == "__main__":
    main()
