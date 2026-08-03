import os
import json
import urllib.request

def generate_infinite_code(prompt):
    """
    Connects to a Cloud LLM (like Google Gemini) using a free API key.
    This unlocks infinite generation without using local GPU power.
    """
    api_key = os.environ.get("GEMINI_API_KEY")
    
    print(f"☁️ [CLOUD BRAIN] Processing request: '{prompt}'...")
    
    if not api_key:
        return """🛑 [CLOUD BRAIN] Missing API Key!
💡 To unlock Infinite Generation:
1. Get a free key from Google AI Studio (Gemini).
2. Run this in your terminal: export GEMINI_API_KEY="your_key_here"
3. Try your command again!"""

    try:
        # Actual HTTP request to Google Gemini API
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={api_key}"
        headers = {'Content-Type': 'application/json'}
        payload = {
            "contents": [{"parts": [{"text": f"Write only the python code for this request, no markdown formatting or explanations: {prompt}"}]}]
        }
        
        req = urllib.request.Request(url, data=json.dumps(payload).encode('utf-8'), headers=headers, method='POST')
        
        with urllib.request.urlopen(req) as response:
            data = json.loads(response.read().decode('utf-8'))
            generated_code = data['candidates'][0]['content']['parts'][0]['text']
            
            # Clean markdown formatting if present
            generated_code = generated_code.replace("```python", "").replace("```", "").strip()
            
            with open("infinite_app.py", "w") as f:
                f.write(generated_code)
                
            return f"☁️ [CLOUD BRAIN] Success! I used the Cloud API to generate your custom app. Saved as infinite_app.py."
            
    except Exception as e:
        return f"🛑 [CLOUD BRAIN] Failed to connect to the cloud. Error: {e}"

if __name__ == "__main__":
    print(generate_infinite_code("Write a calculator script"))
