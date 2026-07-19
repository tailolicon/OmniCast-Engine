import urllib.request
import urllib.parse
import re
import json
import sys

sys.stdout.reconfigure(encoding='utf-8')

def search_ddg_images(query: str, limit: int = 5) -> list[str]:
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    
    # Step 1: get vqd
    init_url = f"https://duckduckgo.com/?q={urllib.parse.quote(query)}"
    req = urllib.request.Request(init_url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            html = r.read().decode('utf-8', errors='ignore')
    except Exception as e:
        print(f"Error getting vqd: {e}")
        return []
        
    # Find vqd
    # Patterns: vqd=... or vqd: '...' or vqd="..."
    vqd_match = re.search(r'vqd=([0-9-]+)', html)
    if not vqd_match:
        vqd_match = re.search(r'vqd\s*=\s*[\'"]([^\'"]+)[\'"]', html)
    if not vqd_match:
        vqd_match = re.search(r'vqd\s*:\s*[\'"]([^\'"]+)[\'"]', html)
        
    if not vqd_match:
        print("vqd not found in HTML")
        return []
        
    vqd = vqd_match.group(1)
    print(f"Found vqd: {vqd}")
    
    # Step 2: call i.js API
    api_url = f"https://duckduckgo.com/i.js?l=us-en&o=json&q={urllib.parse.quote(query)}&vqd={vqd}&f=,,,"
    req = urllib.request.Request(api_url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            res_json = json.loads(r.read().decode('utf-8'))
    except Exception as e:
        print(f"Error calling API: {e}")
        return []
        
    results = res_json.get("results", [])
    print(f"API returned {len(results)} results")
    urls = []
    for r in results:
        image_url = r.get("image")
        if image_url:
            urls.append(image_url)
            if len(urls) >= limit:
                break
    return urls

if __name__ == "__main__":
    query = "Semaglutide packaging box"
    urls = search_ddg_images(query, 5)
    print(f"Found {len(urls)} images:")
    for u in urls:
        print(f" - {u}")
