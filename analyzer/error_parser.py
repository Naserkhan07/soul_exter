import re

def parse_python_error(stderr_text):
    """
    Given a Python traceback, extracts the file, line number, and error type.
    """
    # Look for the last file trace in the traceback
    trace_pattern = r'File "(.*?)", line (\d+).*?'
    traces = re.findall(trace_pattern, stderr_text)
    
    # Look for the actual error message at the bottom
    error_pattern = r'([A-Za-z]+Error):\s(.*)'
    error_match = re.search(error_pattern, stderr_text)
    
    if traces and error_match:
        file_path, line_num = traces[-1]
        error_type, error_msg = error_match.groups()
        return {
            "file": file_path,
            "line": int(line_num),
            "type": error_type,
            "message": error_msg
        }
    return None
