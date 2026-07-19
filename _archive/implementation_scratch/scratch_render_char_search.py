import os
import sys

sys.stdout.reconfigure(encoding='utf-8')

print("Searching for renderCharacter in JSX files:")
app_dir = 'src/omnicast/api/webui/app'
for f in os.listdir(app_dir):
    if f.endswith('.jsx'):
        path = os.path.join(app_dir, f)
        with open(path, 'r', encoding='utf-8') as file:
            content = file.read()
            if 'renderCharacter' in content:
                print(f"  Found in {f}")
