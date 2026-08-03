import difflib
import ast

def get_defined_names(code):
    """
    Parses python code to find all variable names defined in the current scope.
    """
    tree = ast.parse(code)
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            names.add(node.id)
        elif isinstance(node, ast.arg):
            names.add(node.arg)
    return names

def patch_name_error(file_path, line_num, error_message):
    """
    Attempts to fix a NameError by finding the closest matching defined variable.
    """
    # NameError: name 'price' is not defined
    import re
    match = re.search(r"name '(.*?)' is not defined", error_message)
    if not match:
        return False
        
    undefined_var = match.group(1)
    
    with open(file_path, 'r') as f:
        lines = f.readlines()
        
    full_code = "".join(lines)
    
    try:
        # We might not be able to parse if there's a syntax error, but let's try
        defined_vars = get_defined_names(full_code)
    except SyntaxError:
        return False
        
    if not defined_vars:
        return False
        
    # Find the closest matching variable name (Levenshtein/difflib)
    closest_matches = difflib.get_close_matches(undefined_var, defined_vars, n=1, cutoff=0.6)
    
    if closest_matches:
        replacement = closest_matches[0]
        # Replace the bad variable on the specific line
        bad_line = lines[line_num - 1]
        lines[line_num - 1] = bad_line.replace(undefined_var, replacement)
        
        with open(file_path, 'w') as f:
            f.writelines(lines)
            
        print(f"🔧 JARVIS Healer: Fixed NameError on line {line_num}. Replaced '{undefined_var}' with '{replacement}'.")
        return True
        
    return False

def patch_syntax_error(file_path, line_num, error_message):
    """
    Attempts to fix common syntax errors (e.g., missing colons).
    """
    with open(file_path, 'r') as f:
        lines = f.readlines()
        
    bad_line = lines[line_num - 1]
    
    # Common Fix 1: Missing colon at end of if/for/while/def
    if any(bad_line.strip().startswith(kw) for kw in ['if ', 'for ', 'while ', 'def ', 'class ']):
        if not bad_line.strip().endswith(':'):
            lines[line_num - 1] = bad_line.rstrip() + ':\n'
            with open(file_path, 'w') as f:
                f.writelines(lines)
            print(f"🔧 JARVIS Healer: Fixed SyntaxError on line {line_num}. Added missing colon ':'.")
            return True
            
    return False

def apply_fix(parsed_error):
    if not parsed_error:
        return False
        
    if parsed_error['type'] == 'NameError':
        return patch_name_error(parsed_error['file'], parsed_error['line'], parsed_error['message'])
    elif parsed_error['type'] == 'SyntaxError':
        return patch_syntax_error(parsed_error['file'], parsed_error['line'], parsed_error['message'])
        
    print(f"❌ JARVIS doesn't have a rule for {parsed_error['type']} yet.")
    return False
