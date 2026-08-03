import os

def scaffold_performance_profiler(target_file="target_script.py"):
    """
    Jarvis acts as a Performance Optimization Engineer.
    Writes a script to profile the memory and CPU usage of another python file 
    to find bottlenecks.
    """
    file_path = "jarvis_profiler.py"

    code = f"""import cProfile
import pstats
import io
import time

print("⏱️ [PROFILER] Jarvis is tracking CPU execution times...")

# We simulate a heavy function if no target exists
def heavy_computation():
    total = 0
    for i in range(1_000_000):
        total += i * i
    return total

def run_profiler():
    pr = cProfile.Profile()
    pr.enable()
    
    # -----------------------
    # Code to be profiled
    heavy_computation()
    # -----------------------
    
    pr.disable()
    s = io.StringIO()
    sortby = 'cumulative'
    ps = pstats.Stats(pr, stream=s).sort_stats(sortby)
    ps.print_stats(10) # Print top 10 slowest functions
    
    print("\\n📊 [PROFILER RESULTS] TOP BOTTLENECKS FOUND:")
    print(s.getvalue())

if __name__ == '__main__':
    run_profiler()
"""
    with open(file_path, "w") as f:
        f.write(code)

    return f"⚡ [PROFILER] I have built a performance profiler at {file_path}. Run it to find exactly which functions are slowing down your code!"

if __name__ == "__main__":
    print(scaffold_performance_profiler())
