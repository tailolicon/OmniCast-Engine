import sys
import urllib.parse
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent / "implementation" / "src"))
sys.stdout.reconfigure(encoding='utf-8')

from cloakbrowser import launch_persistent_context

def inspect():
    profile_dir = Path("output/search_profile")
    ctx = launch_persistent_context(str(profile_dir), headless=True, humanize=True)
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    
    query = "Semaglutide syringe packaging"
    url = f"https://duckduckgo.com/?q={urllib.parse.quote(query)}&iax=images&ia=images"
    page.goto(url)
    page.wait_for_timeout(5000)
    
    # Let's inspect the first figure element in detail.
    # We will print all properties and children recursive representation.
    figure = page.query_selector("figure")
    if figure:
        data = page.evaluate("""(el) => {
            function getProps(node) {
                const info = {
                    tagName: node.tagName,
                    className: node.className,
                    attributes: {},
                    text: node.innerText ? node.innerText.substring(0, 50) : ""
                };
                for (let attr of node.attributes) {
                    info.attributes[attr.name] = attr.value;
                }
                info.children = Array.from(node.children).map(getProps);
                return info;
            }
            return getProps(el);
        }""", figure)
        
        import json
        print(json.dumps(data, indent=2))
    else:
        print("No figure found")
        
    ctx.close()

if __name__ == "__main__":
    inspect()
