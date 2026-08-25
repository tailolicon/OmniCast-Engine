#!/bin/sh
# V3 campaign — Chinese video translation stack (Douyin download + zh->vi reup pipeline).
# Sequential, quota-frugal. Order: D1 (download layer) -> D2 (translate/dub pipeline).
cd "/e/Project/OmniCast Engine" || exit 1
GROK="$USERPROFILE/.grok/bin/grok.exe"
BR="docs/research/_briefs/v3"
LOG="$BR/logs"
mkdir -p "$LOG"

run_one() {
  name="$1"; brief="$2"; out="$3"; turns="$4"
  echo "=== [$name] start $(date) turns=$turns ==="
  "$GROK" --prompt-file "$brief" --always-approve --max-turns "$turns" \
    --no-plan --no-subagents --reasoning-effort low --disable-web-search \
    > "$LOG/$name.log" 2>&1
  code=$?
  if [ -s "$out" ]; then
    lines=$(wc -l < "$out")
    echo "=== [$name] DONE exit=$code output=$out lines=$lines ==="
  else
    echo "=== [$name] FAILED exit=$code — no output file $out ==="
    tail -5 "$LOG/$name.log"
    if grep -qiE "quota|rate.?limit|429|credit" "$LOG/$name.log"; then
      echo "=== QUOTA SUSPECTED — stopping campaign ==="
      exit 2
    fi
  fi
}

run_one D1 "$BR/D1_douyin_download.md" "docs/research/V3_D1_DouyinDownload.md" 90
run_one D2 "$BR/D2_reup_pipeline.md"   "docs/research/V3_D2_ReupPipeline.md"  130
echo "=== CAMPAIGN V3 COMPLETE $(date) ==="
