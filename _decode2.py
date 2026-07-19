import pathlib, base64, gzip, re

raw = pathlib.Path("OmniCast Engine (standalone).html").read_text(encoding="utf-8", errors="replace")
BS = chr(92)
strings, i, n = [], 0, len(raw)
while i < n:
    if raw[i] == '"':
        j = i + 1; buf = []
        while j < n:
            d = raw[j]
            if d == BS:
                buf.append(raw[j:j + 2]); j += 2; continue
            if d == '"':
                break
            buf.append(d); j += 1
        strings.append("".join(buf)); i = j + 1
    else:
        i += 1
parts = []
for s in strings:
    t = s.strip()
    if len(t) > 200 and t.startswith("H4sI"):
        try:
            parts.append(gzip.decompress(base64.b64decode(t + "=" * (-len(t) % 4))).decode("utf-8", "replace"))
        except Exception:
            pass
big = "\n".join(parts)
# Extract readable UI-ish string literals from the (minified) JS.
lits = re.findall(r'"([ A-Za-z0-9&/().,:%\-À-ỹ]{3,40})"', big)
import collections
seen = []
sset = set()
KEY = re.compile(r"video|office|render|script|channel|niche|vault|budget|cost|schedule|revenue|upload|youtube|thumbnail|title|voice|avatar|tab|dashboard|pipeline|setting|account|token|compliance|analytic|trend|topic|publish|queue|status|infra", re.I)
for L in lits:
    if KEY.search(L) and L not in sset:
        sset.add(L); seen.append(L)
print("=== candidate UI labels (functions) ===")
for L in sorted(seen, key=str.lower):
    print(" ", L)
print("total", len(seen))
