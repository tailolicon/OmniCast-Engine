import sys
import urllib.parse
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent / "implementation" / "src"))
sys.stdout.reconfigure(encoding='utf-8')

from cloakbrowser import launch_persistent_context

def extract_image():
    profile_dir = Path("output/search_profile")
    ctx = launch_persistent_context(str(profile_dir), headless=True, humanize=True)
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    
    query = "Semaglutide syringe packaging"
    url = f"https://duckduckgo.com/?q={urllib.parse.quote(query)}&iax=images&ia=images"
    page.goto(url)
    page.wait_for_timeout(5000)
    
    # We will search the React Fiber tree for image metadata objects
    results = page.evaluate("""() => {
        const figures = document.querySelectorAll('figure');
        if (figures.length === 0) return ["No figures found"];
        
        // Find react fiber key
        const first = figures[0];
        const keys = Object.keys(first);
        const reactKey = keys.find(k => k.startsWith('__reactFiber') || k.startsWith('__reactProps'));
        if (!reactKey) return ["React key not found"];
        
        // Let's traverse up the react node tree for each figure
        const extracted = [];
        for (let fig of figures) {
            let node = fig[reactKey];
            let found_item = null;
            // Traverse up to find props
            while (node) {
                const props = node.memoizedProps;
                if (props) {
                    // Check if props has something that looks like an image search item
                    // Let's check keys
                    for (let k of Object.keys(props)) {
                        const val = props[k];
                        if (val && typeof val === 'object' && !Array.isArray(val)) {
                            // Check if it has 'image', 'title', 'height', 'width'
                            if ('image' in val && 'title' in val && 'height' in val && 'width' in val) {
                                found_item = val;
                                break;
                            }
                        }
                    }
                }
                if (found_item) break;
                node = node.return;
            }
            if (found_item) {
                extracted.push({
                    title: found_item.title,
                    image: found_item.image,
                    width: found_item.width,
                    height: found_item.height,
                    source: found_item.source,
                    url: found_item.url
                });
            }
        }
        return extracted;
    }""")
    
    print(f"Extracted {len(results)} image items:")
    for idx, r in enumerate(results[:10]):
        print(f"{idx}:")
        print(f"  Title:  {r.get('title')}")
        print(f"  Image:  {r.get('image')}")
        print(f"  Dims:   {r.get('width')}x{r.get('height')}")
        print(f"  URL:    {r.get('url')}")
        print(f"  Source: {r.get('source')}")
        
    ctx.close()

if __name__ == "__main__":
    extract_image()
