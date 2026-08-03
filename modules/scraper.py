import urllib.request
import json

def scrape_data(topic="technology"):
    """
    Scrapes data from public APIs or websites autonomously.
    """
    try:
        # Using a free public API (e.g., GitHub or a mock news API) as an example of autonomous data fetching
        url = "https://api.github.com/search/repositories?q=language:python&sort=stars&order=desc"
        req = urllib.request.Request(url, headers={'User-Agent': 'Jarvis-Scraper/1.0'})
        
        with urllib.request.urlopen(req) as response:
            data = json.loads(response.read().decode())
            
        top_repos = []
        for item in data.get('items', [])[:3]:
            top_repos.append(f"- {item['name']}: {item['description']}")
            
        result = "🕷️ [SCRAPER] I fetched the top trending Python projects online right now:\n" + "\n".join(top_repos)
        return result
    except Exception as e:
        return f"🛑 [SCRAPER] Failed to access the internet. Error: {e}"

if __name__ == "__main__":
    print(scrape_data())
