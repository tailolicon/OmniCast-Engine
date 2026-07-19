from playwright.sync_api import sync_playwright
import urllib.parse
import sys

sys.stdout.reconfigure(encoding='utf-8')

def get_ddg_images(query: str, limit: int = 5) -> list[str]:
    print(f"Launching Playwright for query: {query}")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
        page = browser.new_page()
        url = f"https://duckduckgo.com/?q={urllib.parse.quote(query)}&iax=images&ia=images"
        print(f"Navigating to {url}")
        page.goto(url)
        # Wait for the images container
        try:
            page.wait_for_selector(".tile--img", timeout=10000)
        except Exception as e:
            print(f"Error waiting for .tile--img: {e}")
            # print page HTML snippet
            print(page.content()[:1000])
            browser.close()
            return []
            
        # Extract images
        # We can extract the img src or the data-src
        imgs = page.query_selector_all(".tile--img")
        print(f"Found {len(imgs)} images on page")
        
        urls = []
        for img in imgs:
            src = img.get_attribute("src")
            # Sometimes DDG uses data-src or src starts with //
            if not src:
                src = img.get_attribute("data-src")
            if src:
                if src.startswith("//"):
                    src = "https:" + src
                urls.append(src)
                if len(urls) >= limit:
                    break
        browser.close()
        return urls

if __name__ == "__main__":
    query = "Semaglutide syringe packaging"
    urls = get_ddg_images(query, 5)
    print("Results:")
    for u in urls:
        print(f" - {u}")
