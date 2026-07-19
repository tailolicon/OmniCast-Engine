import re

with open('src/omnicast/api/server.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

for i, line in enumerate(lines):
    if 'active_jobs' in line and '=' in line or 'append' in line or 'pop' in line or 'insert' in line or 'clear' in line:
        print(f"Line {i+1}: {line.strip()}")
    elif 'active_jobs' in line:
        # Check if it's being written to in a dict/list
        print(f"Line {i+1}: {line.strip()}")
