"""One-off: mark junk vault topics (score<=0, no brief metadata) as skipped.

These are raw competitor titles scraped verbatim — producing them risks
near-duplicate content. New discovery runs no longer persist them (junk guard
in server.py); this cleans the rows that already exist.
"""
import sqlite3
from pathlib import Path

db_path = Path(__file__).parent / "output" / "vault.db"
db = sqlite3.connect(db_path)
cur = db.execute(
    "UPDATE topics SET status='skipped' WHERE status='queued' AND score<=0 "
    "AND (content_angle IS NULL OR content_angle='') "
    "AND (pain_point IS NULL OR pain_point='')"
)
db.commit()
print(f"junk topics -> skipped: {cur.rowcount}")
for row in db.execute(
        "SELECT status, count(*) FROM topics GROUP BY status"):
    print(row)
