import urllib.request
import urllib.parse
import json

def search_stack_overflow(error_type, error_message):
    """
    If Jarvis encounters a bug it doesn't know how to fix, 
    it connects to the internet to research the error on StackOverflow.
    """
    print(f"🌐 [WEB] Jarvis is researching '{error_type}' on StackOverflow...")
    
    try:
        # Build the search query using the exact error type
        query = urllib.parse.quote(error_type)
        url = f"https://api.stackexchange.com/2.3/search?order=desc&sort=relevance&intitle={query}&site=stackoverflow"
        
        # Connect to StackOverflow API
        req = urllib.request.Request(url, headers={'User-Agent': 'Jarvis-Agent/1.0'})
        
        with urllib.request.urlopen(req) as response:
            data = json.loads(response.read().decode())
            
        if data.get('items') and len(data['items']) > 0:
            top_result = data['items'][0]
            title = top_result['title']
            link = top_result['link']
            
            # Decode HTML entities in title
            import html
            title = html.unescape(title)
            
            return f"💡 JARVIS FOUND A SOLUTION ONLINE:\n   ↳ Thread: {title}\n   ↳ Link: {link}\n   (I recommend reading this thread to fix the error!)"
        else:
            return "🛑 Jarvis searched the web but could not find a clear solution."
            
    except Exception as e:
        return f"🛑 Jarvis could not connect to the internet to research. Error: {e}"
