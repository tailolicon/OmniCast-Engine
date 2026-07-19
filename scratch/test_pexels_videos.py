import sys
import os
import urllib.parse
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent / "implementation" / "src"))
sys.stdout.reconfigure(encoding='utf-8')

from cloakbrowser import launch_persistent_context

def test_pexels_videos():
    profile_dir = Path("output/search_profile")
    ctx = launch_persistent_context(str(profile_dir), headless=True, humanize=True)
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    page.set_viewport_size({"width": 1280, "height": 800})
    
    query = "medical lab syringe"
    url = f"https://www.pexels.com/search/videos/{urllib.parse.quote(query)}/"
    print(f"Navigating to {url}...")
    page.goto(url)
    page.wait_for_timeout(5000)
    
    # Save a screenshot to debug
    os.makedirs("output", exist_ok=True)
    page.screenshot(path="output/pexels_screenshot.png")
    print("Screenshot saved.")
    
    # Try to find video tags or source tags
    videos = page.query_selector_all("video source")
    if not videos:
        # Fallback: check video elements
        videos = page.query_selector_all("video")
        
    print(f"Found {len(videos)} video sources")
    
    urls = []
    for idx, v in enumerate(videos):
        src = v.get_attribute("src")
        if not src:
            # check inside source tag
            source_el = v.query_selector("source")
            if source_el:
                src = source_el.get_attribute("src")
        
        if src:
            urls.append(src)
            print(f"  {idx}: {src[:120]}")
            
    ctx.close()

if __name__ == "__main__":
    test_pexels_videos()
