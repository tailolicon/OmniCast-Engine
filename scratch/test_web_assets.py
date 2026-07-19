import sys
from pathlib import Path

# Add implementation/src to path
sys.path.append(str(Path(__file__).resolve().parent.parent / "implementation" / "src"))
sys.stdout.reconfigure(encoding='utf-8')

from omnicast.media.providers.web_assets import download_best_web_image

def main():
    out_path = Path("output/test_web_asset.png")
    query = "Semaglutide Wegovy pen injection"
    
    print(f"Testing download_best_web_image with query: '{query}'...")
    success = download_best_web_image(query, out_path, 1920, 1080)
    
    if success:
        print(f"SUCCESS: Image saved to {out_path}")
        # print size
        from PIL import Image
        with Image.open(out_path) as img:
            print(f"Final image size: {img.size}")
    else:
        print("FAILED to download web image.")

if __name__ == "__main__":
    main()
