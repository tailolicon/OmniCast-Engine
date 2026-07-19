import sys
sys.stdout.reconfigure(encoding='utf-8')

with open("e:/Project/OmniCast Engine/implementation/render_real_video.py", "r", encoding="utf-8") as f:
    lines = f.readlines()

keywords = ["def ", "class ", "flow", "imagen", "download", "image", "playwright", "html"]
for idx, line in enumerate(lines):
    line_num = idx + 1
    for kw in keywords:
        if kw in line:
            print(f"{line_num}: {line.strip()}")
            break
