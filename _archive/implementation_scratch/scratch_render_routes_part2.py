import sys

sys.stdout.reconfigure(encoding='utf-8')

with open('src/omnicast/api/render_routes.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

print("render_routes.py : upload_video body:")
for j in range(260, 350):
    if j < len(lines):
        try:
            print(f"  {j+1}: {lines[j].rstrip()}")
        except Exception:
            clean = lines[j].encode('ascii', errors='replace').decode('ascii')
            print(f"  {j+1}: {clean.rstrip()}")
