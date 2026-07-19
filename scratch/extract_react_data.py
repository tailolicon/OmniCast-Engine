import sys
import urllib.parse
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent / "implementation" / "src"))
sys.stdout.reconfigure(encoding='utf-8')

from cloakbrowser import launch_persistent_context

def extract():
    profile_dir = Path("output/search_profile")
    ctx = launch_persistent_context(str(profile_dir), headless=True, humanize=True)
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    
    query = "Semaglutide syringe packaging"
    url = f"https://duckduckgo.com/?q={urllib.parse.quote(query)}&iax=images&ia=images"
    page.goto(url)
    page.wait_for_timeout(5000)
    
    # We will evaluate a script that searches React keys on the figure elements
    react_data = page.evaluate("""() => {
        const figure = document.querySelector('figure');
        if (!figure) return "No figure element found";
        
        // Find react fiber or props key
        const keys = Object.keys(figure);
        const reactKey = keys.find(k => k.startsWith('__reactFiber') || k.startsWith('__reactProps') || k.startsWith('__reactEvents'));
        if (!reactKey) return "React internal key not found. Available keys: " + keys.join(', ');
        
        // Let's traverse the React object
        const node = figure[reactKey];
        
        // We want to find a data structure containing the image info.
        // Let's serialize the react node properties (first 2 levels)
        function clean(obj, depth = 0) {
            if (depth > 5) return "...";
            if (obj === null || obj === undefined) return obj;
            if (typeof obj !== 'object') {
                if (typeof obj === 'string' && obj.startsWith('http')) return obj;
                if (typeof obj === 'number' || typeof obj === 'boolean') return obj;
                return typeof obj;
            }
            if (Array.isArray(obj)) {
                return obj.map(item => clean(item, depth + 1));
            }
            const res = {};
            for (let k in obj) {
                if (k.startsWith('__') || k === 'stateNode' || k === 'child' || k === 'return' || k === 'sibling' || k === 'memoizedState') {
                    continue; // skip loops
                }
                try {
                    res[k] = clean(obj[k], depth + 1);
                } catch(e) {
                    res[k] = "error";
                }
            }
            return res;
        }
        
        return {
            reactKey: reactKey,
            data: clean(node)
        };
    }""")
    
    import json
    print(json.dumps(react_data, indent=2))
    
    ctx.close()

if __name__ == "__main__":
    extract()
