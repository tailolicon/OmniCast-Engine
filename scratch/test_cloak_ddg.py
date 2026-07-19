import sys
import os
import urllib.parse
from pathlib import Path

# Add implementation/src to sys.path so we can import things if needed
sys.path.append(str(Path(__file__).resolve().parent.parent / "implementation" / "src"))

sys.stdout.reconfigure(encoding='utf-8')

from cloakbrowser import launch_persistent_context

def test_cloak_ddg():
    profile_dir = Path("output/search_profile")
    profile_dir.mkdir(parents=True, exist_ok=True)
    
    print("Launching CloakBrowser...")
    ctx = launch_persistent_context(
        str(profile_dir),
        headless=True,
        humanize=True,
    )
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    page.set_viewport_size({"width": 1280, "height": 800})
    
    query = "Semaglutide syringe packaging"
    url = f"https://duckduckgo.com/?q={urllib.parse.quote(query)}&iax=images&ia=images"
    print(f"Navigating to {url}")
    page.goto(url)
    
    page.wait_for_timeout(5000)
    
    os.makedirs("output", exist_ok=True)
    screenshot_path = "output/cloak_ddg_screenshot.png"
    page.screenshot(path=screenshot_path)
    print(f"Screenshot saved to {screenshot_path}")
    
    # Try to find images
    # DDG image tile selector in react version: we can look for any img tags that contain thumbnail URLs
    # Or query selector for img elements
    imgs = page.query_selector_all("img")
    print(f"Total img tags: {len(imgs)}")
    
    urls = []
    for idx, img in enumerate(imgs):
        src = img.get_attribute("src")
        cls = img.get_attribute("class")
        # print first few images to see if they are search results
        if idx < 20:
            print(f"  {idx}: class={cls}, src={src[:80] if src else 'None'}")
        
        # DDG thumbnail images typically have "tse" or "bing.net" or "duckduckgo.com/iu" in the src URL
        # Let's filter out tracking pixels, icons, etc.
        if src and ("tse" in src or "bing.net" in src or "duckduckgo.com/iu" in src or "lh3.googleusercontent" in src):
            if src.startswith("//"):
                src = "https:" + src
            if src not in urls:
                urls.append(src)
                
    print(f"Filtered to {len(urls)} potential search result images:")
    for u in urls[:5]:
        print(f"  - {u}")
        
    ctx.close()

if __name__ == "__main__":
    test_cloak_ddg()
