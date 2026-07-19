import urllib.request
import urllib.parse
import json
import re
import sys

sys.stdout.reconfigure(encoding='utf-8')

def search_bing_images(query: str, limit: int = 5) -> list[str]:
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    url = f"https://www.bing.com/images/search?q={urllib.parse.quote(query)}"
    print(f"Searching: {url}")
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            html = response.read().decode('utf-8', errors='ignore')
    except Exception as e:
        print(f"Error fetching Bing: {e}")
        return []
    
    # Bing stores image info in class "iusc" with attribute m='{"murl":"..."}'
    # Let's find all occurrences of m='{...}' or m="{...}"
    matches = re.findall(r'm="([^"]+)"', html)
    if not matches:
        matches = re.findall(r"m='([^']+)'", html)
        
    urls = []
    for m in matches:
        # Unescape HTML entities in JSON
        m_json = m.replace("&quot;", '"').replace("&#39;", "'").replace("&amp;", "&")
        try:
            data = json.loads(m_json)
            murl = data.get("murl")
            if murl and murl.startswith("http"):
                urls.append(murl)
                if len(urls) >= limit:
                    break
        except Exception:
            continue
            
    return urls

if __name__ == "__main__":
    query = "Semaglutide syringe"
    urls = search_bing_images(query, 5)
    print(f"Found {len(urls)} images:")
    for u in urls:
        print(f" - {u}")
