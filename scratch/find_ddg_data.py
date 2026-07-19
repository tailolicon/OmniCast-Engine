import sys
import urllib.parse
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent / "implementation" / "src"))
sys.stdout.reconfigure(encoding='utf-8')

from cloakbrowser import launch_persistent_context

def find_data():
    profile_dir = Path("output/search_profile")
    ctx = launch_persistent_context(str(profile_dir), headless=True, humanize=True)
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    
    query = "Semaglutide syringe packaging"
    url = f"https://duckduckgo.com/?q={urllib.parse.quote(query)}&iax=images&ia=images"
    page.goto(url)
    page.wait_for_timeout(5000)
    
    # Let's inspect window object properties
    ddg_props = page.evaluate("() => Object.keys(window).filter(k => k.includes('DDG') || k.includes('ddg') || k.includes('page') || k.includes('data') || k.includes('state'))")
    print("Interesting window properties:", ddg_props)
    
    # Let's see if we can find scripts containing JSON
    scripts = page.query_selector_all("script")
    print(f"Total script tags: {len(scripts)}")
    for idx, s in enumerate(scripts):
        text = s.inner_text()
        if not text:
            continue
        if "tse" in text or "OIP" in text or "image" in text:
            print(f"Script {idx} length: {len(text)}")
            if len(text) < 1000:
                print(text)
            else:
                print(text[:300] + " ... [TRUNCATED] ... " + text[-300:])
            print("-" * 50)
            
    # Let's search if there's a React-specific state object or similar on the window
    # e.g., if there's a global array of images.
    image_data = page.evaluate("""() => {
        // Search all script tags for a pattern like "regions" or similar
        const scripts = Array.from(document.querySelectorAll('script'));
        for (let s of scripts) {
            const t = s.innerText || "";
            if (t.includes('vqd=') && t.includes('tse')) {
                return t.substring(0, 1000);
            }
        }
        return "Not found in script contents";
    }""")
    print("Found image data in script:", image_data[:500])

    ctx.close()

if __name__ == "__main__":
    find_data()
