import os
import sys

sys.stdout.reconfigure(encoding='utf-8')

print("Searching for RightPanel:")
for root, dirs, files in os.walk('src/omnicast/api/webui'):
    for f in files:
        if f.endswith('.jsx') or f.endswith('.html'):
            path = os.path.join(root, f)
            with open(path, 'r', encoding='utf-8') as file:
                lines = file.readlines()
            for i, line in enumerate(lines):
                if 'RightPanel' in line and ('function' in line or 'const' in line or 'class' in line):
                    print(f"  {path} : Line {i+1}: {line.strip()}")
