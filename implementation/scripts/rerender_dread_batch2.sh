#!/usr/bin/env bash
# Re-render parking + hospital with the validated audio/card overhaul
# (Edge Christopher voice, event-SFX, story beats). Sequential = no RAM thrash.
set -u
cd "$(dirname "$0")/.." || exit 1
for kw in 0709 0715; do
  PD=$(ls -d output/products/true_dread_files_us/*"$kw"* 2>/dev/null | head -1)
  [ -z "$PD" ] && { echo "[batch2] no product for $kw"; continue; }
  echo "[batch2] ===== rendering $(basename "$PD") ====="
  python -X utf8 render_real_video.py --script "$PD/script.txt" \
    --channel true_dread_files_us --subtitles --out "$PD/video_v2.mp4"
  echo "[batch2] ===== done $(basename "$PD") rc=$? ====="
done
echo "[batch2] ALL DONE"
