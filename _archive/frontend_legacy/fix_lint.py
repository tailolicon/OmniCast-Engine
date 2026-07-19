import re
import os

path = r"E:\Project\OmniCast Engine\frontend\src\App.jsx"
with open(path, "r", encoding="utf-8") as f:
    content = f.read()

# Fix catch(e) to catch
content = re.sub(r'catch\s*\(\s*[a-zA-Z_]\w*\s*\)\s*\{\s*alert\(', r'catch { alert(', content)
content = re.sub(r'catch\s*\(\s*[a-zA-Z_]\w*\s*\)\s*\{\s*/\*\s*surfaced via OfflineBanner\s*\*/\s*\}', r'catch { /* surfaced via OfflineBanner */ }', content)
content = re.sub(r'catch\s*\(\s*e\s*\)\s*\{\s*/\*\s*ignore\s*\*/\s*\}', r'catch { /* ignore */ }', content)

# Fix const d = await r.json() where d is unused
content = re.sub(r'const\s+[a-zA-Z_]\w*\s*=\s*await\s+r\.json\(\)\s*;\s*if\s*\(r\.status\s*===', r'await r.json();\n            if (r.status ===', content)
content = re.sub(r'const\s+d\s*=\s*await\s+r\.json\(\)\s*;\s*if\s*\(d\.status\s*===', r'const d = await r.json();\n            if (d.status ===', content)

# There are some places where d is completely unused
content = re.sub(r'const\s+d\s*=\s*await\s+r\.json\(\)\s*;\s*refetch\(\);', r'await r.json();\n            refetch();', content)
content = re.sub(r'const\s+d\s*=\s*await\s+r\.json\(\)\s*;\s*alert\(\'No active job found\.\'\);', r'await r.json();\n            alert(\'No active job found.\');', content)


# Fix the 'const d = await r.json();' generic unused
content = re.sub(r'const\s+[a-zA-Z_]\w*\s*=\s*await\s+r\.json\(\)\s*;\n(\s*)if\s*\(r\.status\s*===', r'await r.json();\n\1if (r.status ===', content)

with open(path, "w", encoding="utf-8") as f:
    f.write(content)

print("Fixed ESLint syntax issues.")
