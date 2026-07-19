from playwright.sync_api import sync_playwright
import urllib.parse
import sys
import os

sys.stdout.reconfigure(encoding='utf-8')

def debug_ddg():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
        page = browser.new_page()
        # Set large viewport
        page.set_viewport_size({"width": 1280, "height": 800})
        query = "Semaglutide syringe packaging"
        url = f"https://duckduckgo.com/?q={urllib.parse.quote(query)}&iax=images&ia=images"
        print(f"Navigating to {url}")
        page.goto(url)
        
        # Sleep for a bit to let JS load
        page.wait_for_timeout(5000)
        
        # Save screenshot
        os.makedirs("output", exist_ok=True)
        screenshot_path = "output/ddg_screenshot.png"
        page.screenshot(path=screenshot_path)
        print(f"Screenshot saved to {screenshot_path}")
        
        # Find all images or anchors
        img_elements = page.query_selector_all("img")
        print(f"Total img tags: {len(img_elements)}")
        for idx, img in enumerate(img_elements[:15]):
            src = img.get_attribute("src")
            cls = img.get_attribute("class")
            print(f" {idx}: class={cls}, src={src[:80] if src else 'None'}")
            
        # Let's list some element class names
        div_classes = page.evaluate("""() => {
            const classes = new Set();
            document.querySelectorAll('div, a, img').forEach(el => {
                if (el.className) classes.add(el.tagName + '.' + el.className);
            });
            return Array.from(classes).slice(0, 50);
        }""")
        print("Some classes on page:")
        for c in div_classes:
            print(f"  {c}")
            
        browser.close()

if __name__ == "__main__":
    debug_ddg()
