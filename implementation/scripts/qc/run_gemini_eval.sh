#!/usr/bin/env bash
# External QC round: sample frames from a rendered video, hand them plus the
# audio facts to Gemini 3.8 Flash through the Antigravity CLI (subscription,
# no API billing) under the anti-sycophancy harness, and print its verdict.
#
#   scripts/qc/run_gemini_eval.sh output/real/video.mp4 [frames=24] [outdir]
set -euo pipefail
VIDEO="${1:?video path}"
N="${2:-24}"
OUT="${3:-output/_qc/$(basename "${VIDEO%.*}")_$(date +%H%M%S)}"
HERE="$(cd "$(dirname "$0")" && pwd)"
mkdir -p "$OUT"

DUR=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$VIDEO")
LUFS=$(ffmpeg -nostats -i "$VIDEO" -af ebur128=framelog=quiet -f null - 2>&1 | grep -E "^\s+I:" | tail -1 | awk '{print $2}')
W=$(ffprobe -v error -select_streams v:0 -show_entries stream=width,height -of csv=p=0 "$VIDEO")

# Evenly spaced frames, skipping the first/last 2%.
python3 - "$VIDEO" "$N" "$OUT" "$DUR" <<'EOF'
import subprocess, sys
video, n, out, dur = sys.argv[1], int(sys.argv[2]), sys.argv[3], float(sys.argv[4])
for k in range(n):
    t = dur * (0.02 + 0.96 * k / max(1, n - 1))
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{t:.2f}", "-i", video,
                    "-frames:v", "1", "-vf", "scale=960:-2", f"{out}/f{k:02d}_{int(t):04d}s.jpg"])
EOF

FRAMES=$(ls "$OUT"/f*.jpg | xargs -n1 realpath | tr '\n' ' ')
PROMPT="$(cat "$HERE/EVAL_PROMPT.md")

FACTS: duration=${DUR}s, integrated loudness=${LUFS} LUFS, size=${W}.
FRAMES (view every one of them before answering): ${FRAMES}"

agy -p "$PROMPT" --model gemini-3.8-flash --effort "${QC_EFFORT:-high}" --dangerously-skip-permissions | tee "$OUT/verdict.md"
echo "frames + verdict in $OUT"
