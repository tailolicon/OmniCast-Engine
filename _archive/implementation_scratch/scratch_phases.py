import sys
import re

# Set output encoding to utf-8
sys.stdout.reconfigure(encoding='utf-8')

with open('src/omnicast/api/server.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

print("Calls to set_active_job, write_pipeline_event, set_active_job_progress in server.py:")
for i, line in enumerate(lines):
    if any(x in line for x in ['set_active_job', 'write_pipeline_event', 'set_active_job_progress']):
        print(f"Line {i+1}:")
        for j in range(max(0, i-2), min(len(lines), i+3)):
            try:
                print(f"  {j+1}: {lines[j].rstrip()}")
            except Exception as e:
                # Fallback to ascii representation or ignore
                clean = lines[j].encode('ascii', errors='replace').decode('ascii')
                print(f"  {j+1}: {clean.rstrip()}")
        print("-" * 40)
