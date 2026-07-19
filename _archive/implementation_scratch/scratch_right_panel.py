import sys

sys.stdout.reconfigure(encoding='utf-8')

with open('src/omnicast/api/webui/index.html', 'r', encoding='utf-8') as f:
    lines = f.readlines()

for i, line in enumerate(lines):
    if 'function RightPanel' in line:
        print(f"Line {i+1}:")
        for j in range(max(0, i-2), min(len(lines), i+60)):
            try:
                print(f"  {j+1}: {lines[j].rstrip()}")
            except Exception:
                clean = lines[j].encode('ascii', errors='replace').decode('ascii')
                print(f"  {j+1}: {clean.rstrip()}")
        print("-" * 40)
