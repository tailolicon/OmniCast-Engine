import urllib.request
import urllib.parse
import re
import json
import sys

sys.stdout.reconfigure(encoding='utf-8')

def search_yahoo_images(query: str, limit: int = 5) -> list[str]:
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    url = f"https://images.search.yahoo.com/search/images?p={urllib.parse.quote(query)}"
    print(f"Searching Yahoo: {url}")
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            html = r.read().decode('utf-8', errors='ignore')
    except Exception as e:
        print(f"Error fetching Yahoo Images: {e}")
        return []

    print(f"HTML size: {len(html)}")
    
    # Yahoo Images has list items containing metadata like {"rurl": "...", "iurl": "...", "key": "..."}
    # Often in a JSON object inside <li class="ld" ... data-ld='{...}'> or similar
    # Let's find matches for: "imgurl":"http..." or "iurl":"http..."
    # Let's do a broad search of all URLs ending in common extensions or json patterns
    urls = []
    
    # Yahoo's JSON attributes inside list items:
    # metadata looks like: {"ou":"http...", "ouHeight":..., "ouWidth":..., "ru":"http..."}
    # or {"iurl":"http..."} or {"ou":"https://..."}
    # Let's try to find all occurrences of "ou":"https?://[^"]+" or "iurl":"https?://[^"]+"
    for match in re.finditer(r'"(ou|iurl)"\s*:\s*"([^"]+)"', html):
        img_url = match.group(2).replace("\\/", "/")
        if img_url.startswith("http") and img_url not in urls:
            urls.append(img_url)
            if len(urls) >= limit:
                break
                
    if not urls:
        # Fallback to general URLs inside HTML attributes
        # Let's print a small snippet to see the page structure
        print("No urls found via json regex. Page context:")
        idx = html.find("<li")
        if idx != -1:
            print(html[idx:idx+1500])
            
    return urls

if __name__ == "__main__":
    query = "Semaglutide syringe"
    urls = search_yahoo_images(query, 5)
    print(f"Found {len(urls)} images:")
    for u in urls:
        print(f" - {u}")
