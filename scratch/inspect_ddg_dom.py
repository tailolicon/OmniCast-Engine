import sys
import os
import urllib.parse
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent / "implementation" / "src"))

sys.stdout.reconfigure(encoding='utf-8')

from cloakbrowser import launch_persistent_context

def inspect_ddg_dom():
    profile_dir = Path("output/search_profile")
    ctx = launch_persistent_context(str(profile_dir), headless=True, humanize=True)
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    
    query = "Semaglutide syringe packaging"
    url = f"https://duckduckgo.com/?q={urllib.parse.quote(query)}&iax=images&ia=images"
    page.goto(url)
    page.wait_for_timeout(5000)
    
    # Let's inspect the parent elements of the images that have external-content in their src
    imgs = page.query_selector_all("img")
    count = 0
    for img in imgs:
        src = img.get_attribute("src")
        if src and "external-content" in src:
            # Let's print the parent hierarchy HTML
            parent = img.evaluate_handle("el => el.parentElement")
            parent_html = page.evaluate("el => el.outerHTML", parent)
            print(f"--- MATCH {count} ---")
            print(parent_html[:1000]) # Print first 1000 chars of parent
            print("-" * 40)
            
            # Let's also check if there are parent anchors (a) and what href/data they have
            grandparent = img.evaluate_handle("el => el.parentElement.parentElement")
            gp_html = page.evaluate("el => el.outerHTML", grandparent)
            print(f"Grandparent HTML:")
            print(gp_html[:1000])
            print("=" * 80)
            
            count += 1
            if count >= 3:
                break
                
    ctx.close()

if __name__ == "__main__":
    inspect_ddg_dom()
