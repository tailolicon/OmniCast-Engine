import os
import sys

sys.stdout.reconfigure(encoding='utf-8')

root_dir = "e:/Project/OmniCast Engine/implementation"
for root, dirs, files in os.walk(root_dir):
    # skip venv, __pycache__, etc.
    if any(p in root for p in [".venv", "__pycache__", ".git"]):
        continue
    for file in files:
        if file.endswith(".py"):
            path = os.path.join(root, file)
            try:
                with open(path, "r", encoding="utf-8") as f:
                    content = f.read()
                if "cloakbrowser" in content or "CloakBrowser" in content:
                    print(f"Found in: {path}")
            except Exception:
                pass
