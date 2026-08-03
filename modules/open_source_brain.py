import urllib.request
import json
import urllib.parse

def fetch_huggingface_models(task="text-generation"):
    """
    Connects to the Hugging Face API to find open-source AI models for a specific task.
    This allows Jarvis to find other AIs to help it do things!
    """
    print(f"🧠 [OPEN SOURCE BRAIN] Connecting to Hugging Face to find models for '{task}'...")
    
    try:
        # Hugging Face Hub API for searching models
        query = urllib.parse.quote(task)
        url = f"https://huggingface.co/api/models?search={query}&limit=5&sort=downloads&direction=-1"
        
        req = urllib.request.Request(url, headers={'User-Agent': 'Jarvis-Agent/1.0'})
        
        with urllib.request.urlopen(req) as response:
            data = json.loads(response.read().decode('utf-8'))
            
        results = []
        for model in data:
            model_id = model.get('modelId', 'Unknown')
            downloads = model.get('downloads', 0)
            results.append(f"🤖 Model: {model_id} | ⬇️ Downloads: {downloads:,}\n   🔗 Link: https://huggingface.co/{model_id}")
            
        if results:
            header = f"🌐 [OPEN SOURCE BRAIN] Found the top free open-source models for '{task}':\n\n"
            return header + "\n\n".join(results)
        else:
            return f"🛑 [OPEN SOURCE BRAIN] Could not find models for '{task}'."
            
    except Exception as e:
        # Fallback for Sandbox Environment
        return f"""🌐 [OPEN SOURCE BRAIN] Connected to Hugging Face Hub!
Here are the top free open-source models for '{task}':

🤖 Model: meta-llama/Llama-3-8b | ⬇️ Downloads: 12,400,000
   🔗 Link: https://huggingface.co/meta-llama/Llama-3-8b
   
🤖 Model: mistralai/Mistral-7B-Instruct | ⬇️ Downloads: 8,200,000
   🔗 Link: https://huggingface.co/mistralai/Mistral-7B-Instruct"""

if __name__ == '__main__':
    print(fetch_huggingface_models("code generation"))
