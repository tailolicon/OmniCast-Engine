import urllib.request
import urllib.parse
import sys

sys.stdout.reconfigure(encoding='utf-8')

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}
url = f"https://www.bing.com/images/search?q=Semaglutide%20syringe"
req = urllib.request.Request(url, headers=headers)
with urllib.request.urlopen(req, timeout=10) as r:
    html = r.read().decode('utf-8', errors='ignore')

print(f"HTML length: {len(html)}")
# find occurrences of "iusc"
print(f"iusc count: {html.count('iusc')}")
print(f"m= count: {html.count('m=')}")

# print a small chunk around the first "iusc"
idx = html.find("iusc")
if idx != -1:
    print("Context around iusc:")
    print(html[max(0, idx-100):min(len(html), idx+300)])
