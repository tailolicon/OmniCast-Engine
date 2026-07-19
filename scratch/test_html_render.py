import sys
from pathlib import Path

# Add implementation/src and implementation/ to path
sys.path.append(str(Path(__file__).resolve().parent.parent / "implementation"))
sys.path.append(str(Path(__file__).resolve().parent.parent / "implementation" / "src"))

sys.stdout.reconfigure(encoding='utf-8')

import html_overlay
from render_real_video import Scene

def main():
    if not html_overlay.available():
        print("Playwright is NOT available in html_overlay")
        return
        
    print("Playwright is available. Testing render_text_overlay...")
    sc = Scene(
        heading="Trigger Foods: Raw Cruciferous Vegetables",
        narration="Food number one: raw cruciferous vegetables — think kale, broccoli, cabbage, all that raw roughage. They are packed with insoluble fiber and sulfur."
    )
    
    out_png = Path("output/test_html_overlay.png")
    out_png.parent.mkdir(parents=True, exist_ok=True)
    
    try:
        html_overlay.render_text_overlay(sc, 0, 7, out_png, 1920, 1080)
        if out_png.exists():
            print(f"SUCCESS: Overlay rendered to {out_png}")
            # check size
            from PIL import Image
            with Image.open(out_png) as img:
                print(f"Verify overlay image size: {img.size}, mode: {img.mode}")
        else:
            print("FAILED: File was not created.")
    except Exception as e:
        print(f"ERROR rendering HTML overlay: {e}")
    finally:
        html_overlay.close()

if __name__ == "__main__":
    main()
