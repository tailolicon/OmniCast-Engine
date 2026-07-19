import sys
import json
from pathlib import Path

# Add implementation/src to path
sys.path.append(str(Path(__file__).resolve().parent.parent / "implementation"))
sys.path.append(str(Path(__file__).resolve().parent.parent / "implementation" / "src"))

sys.stdout.reconfigure(encoding='utf-8')

# Import functions from render_real_video
from render_real_video import Scene, parse_script, generate_storyboard, _web_cache_path
from omnicast.media.providers.web_assets import download_best_web_image

TEST_SCRIPT_CONTENT = """
Ozempic and Wegovy pens are selling out worldwide, causing a massive supply shortage for Novo Nordisk and prompting Eli Lilly to speed up Zepbound production.
---
[The Nausea Solution]
Low vitamin B12 levels are a common hidden cause that doubles your nausea, which is why optimizing B12 status is the very first thing to check.
"""

def main():
    print("Parsing test script...")
    scenes = parse_script(TEST_SCRIPT_CONTENT)
    print(f"Parsed {len(scenes)} scenes:")
    for idx, sc in enumerate(scenes):
        print(f"  Scene {idx}: [{sc.heading}] {sc.narration}")
        
    print("\nCalling LLM to generate storyboard...")
    channel_meta = {
        "brand_voice": "Evidence-based medical relief, scientific but empathetic",
        "audience": {
            "pain_points": ["GLP-1 nausea", "weight loss plateaus", "deficiencies"]
        }
    }
    board = generate_storyboard(scenes, channel_meta)
    if not board:
        print("Error: generate_storyboard returned None")
        return
        
    print("\nGenerated Storyboard:")
    print(json.dumps(board, indent=2))
    
    print("\nProcessing storyboard items for web search images...")
    work_dir = Path("output/test_pipeline_run")
    work_dir.mkdir(parents=True, exist_ok=True)
    
    W, H = 1920, 1080
    
    for i, cell in enumerate(board):
        visual_type = cell.get("visual_type", "generated_image")
        query = (cell.get("search_query") or "").strip()
        print(f"\nScene {i}: visual_type = '{visual_type}'")
        if visual_type == "web_search_image" and query:
            dest = work_dir / f"scene_{i:02d}_illu.png"
            print(f"  Web search query: '{query}'")
            print(f"  Downloading to {dest}...")
            
            # Use direct downloader
            success = download_best_web_image(query, dest, W, H)
            if success:
                print(f"  SUCCESS: Web image downloaded and resized to Cover 1920x1080")
                from PIL import Image
                with Image.open(dest) as img:
                    print(f"  Verify size: {img.size}, format: {img.format}")
            else:
                print("  FAILED to download web image.")
        else:
            print("  (Standard generated image - skipped for this test)")

if __name__ == "__main__":
    main()
