import re

with open('src/omnicast/api/server.py', 'r', encoding='utf-8') as f:
    content = f.read()

phases = re.findall(r'[\'\"]phase[\'\"]\s*:\s*[\'\"]([^\'\"]+)[\'\"]', content)
stages = re.findall(r'[\'\"]stage[\'\"]\s*:\s*[\'\"]([^\'\"]+)[\'\"]', content)

print("Phases in server.py:", set(phases))
print("Stages in server.py:", set(stages))

# Let's search for "active_jobs" and print the surrounding lines.
lines = content.splitlines()
matches = []
for i, line in enumerate(lines):
    if "active_jobs" in line or "phase" in line:
        # print range
        start = max(0, i - 1)
        end = min(len(lines), i + 2)
        matches.append(f"Lines {start+1}-{end+1}:\n" + "\n".join(f"  {lines[j]}" for j in range(start, end)))

print("\nJobs dict matches:")
for m in matches[:15]:
    print(m)
