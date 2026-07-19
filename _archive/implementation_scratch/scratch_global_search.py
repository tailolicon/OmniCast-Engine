import os
import re
import sys

sys.stdout.reconfigure(encoding='utf-8')

print("Global search for pipeline state updates in python files:")
root_dir = 'src/omnicast'
pattern = re.compile(r'(set_active_job|write_pipeline_event|set_active_job_progress)')

for dirpath, dirnames, filenames in os.walk(root_dir):
    for filename in filenames:
        if filename.endswith('.py'):
            filepath = os.path.join(dirpath, filename)
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    lines = f.readlines()
                for i, line in enumerate(lines):
                    if pattern.search(line):
                        print(f"{filepath} : Line {i+1}: {line.strip()}")
            except Exception as e:
                pass
